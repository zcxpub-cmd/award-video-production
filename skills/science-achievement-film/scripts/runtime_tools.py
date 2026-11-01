#!/usr/bin/env python3
"""Local dependency diagnostics and conservative task bookkeeping; never submits jobs.

No third-party implementation is vendored. Diagnostics execute only version/help
introspection on configured local binaries. Ledger contents never contain request
bodies, auth values, service responses, or arbitrary subprocess output.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

DEFAULTS = {
    "schema_version": 1,
    "tools": {
        "ffmpeg": ["ffmpeg"],
        "ffprobe": ["ffprobe"],
        "blender": ["blender"],
        "freecad": ["FreeCAD"],
        "soffice": ["soffice"],
        "pdfinfo": ["pdfinfo"], "pdftotext": ["pdftotext"], "pdftoppm": ["pdftoppm"],
        "tesseract": ["tesseract"], "whisper": ["whisper"],
        "crv": ["crv"],
    },
    "files": {"davinci_client": "", "voicestudio_app": "", "wps_app": ""},
    "secret_files": {"seedance_api_key": "", "seedance_base_url": ""},
    "local_services": {"voicestudio": "http://127.0.0.1:3900/health"},
}
FILTERS = ("ass", "subtitles", "freezedetect", "blackdetect", "silencedetect", "loudnorm", "ebur128", "xfade", "acrossfade")
KINDS = ("local-analysis", "local-render", "local-tts", "seedance", "davinci-render")
STATES = ("prepared", "submitted", "running", "succeeded", "failed", "unknown", "cancelled")
NEXT = {
    "prepared": {"submitted", "running", "cancelled"},
    "submitted": {"running", "succeeded", "failed", "unknown", "cancelled"},
    "running": {"succeeded", "failed", "unknown", "cancelled"},
    "unknown": {"running", "succeeded", "failed", "cancelled"},
    "failed": {"cancelled"}, "succeeded": set(), "cancelled": set(),
}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_config(path=None):
    result = json.loads(json.dumps(DEFAULTS))
    for name in result["tools"]:
        override = os.environ.get("SCIENCE_FILM_" + name.upper())
        if override:
            result["tools"][name].insert(0, override)
    if path:
        custom = json.loads(Path(path).read_text(encoding="utf-8"))
        if set(custom) - set(DEFAULTS) or custom.get("schema_version", 1) != 1:
            raise ValueError("unsupported config schema or fields")
        for key, value in custom.items():
            if key != "schema_version":
                if not isinstance(value, dict) or set(value) - set(DEFAULTS[key]):
                    raise ValueError("unsupported config entries")
                result[key].update(value)
    for entries in (result["files"], result["secret_files"], result["local_services"]):
        if any(not isinstance(v, str) for v in entries.values()):
            raise ValueError("config paths and service URLs must be nonempty strings")
    for candidates in result["tools"].values():
        if not isinstance(candidates, list) or not candidates or any(not isinstance(p, str) or not p for p in candidates):
            raise ValueError("tool paths must be nonempty lists of executable paths")
    return result


def resolve_tool(candidates):
    for value in candidates:
        expanded = str(Path(value).expanduser())
        found = expanded if "/" in expanded else shutil.which(expanded)
        if found and Path(found).is_file() and os.access(found, os.X_OK):
            return str(Path(found).resolve())
    return None


def _probe(argv):
    """Fixed, read-only probes only; raw output stays private to the parser."""
    try:
        with tempfile.TemporaryFile() as output:
            run = subprocess.run(argv, stdout=output, stderr=subprocess.STDOUT, timeout=15, check=False)
            output.seek(0)
            return run.returncode, output.read(256 * 1024).decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def parse_filters(output):
    names = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and re.fullmatch(r"[TSC.]{2,3}", fields[0]):
            names.add(fields[1])
    return {name: name in names for name in FILTERS}


def local_health(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("health check permits only credential-free loopback HTTP URLs")
    # Do not follow redirects to a remote server or return potentially sensitive bodies.
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=3) as response:
            return {"reachable": True, "http_status": response.status}
    except Exception:
        return {"reachable": False, "http_status": None}


def doctor(config, check_services=False):
    report = {"schema_version": 1, "checked_at": now(), "scope": "read-only environment probe; no generation or GUI input", "tools": {}, "files": {}, "secret_files": {}, "python": {"executable": sys.executable}, "services": {}}
    for name, candidates in config["tools"].items():
        path = resolve_tool(candidates)
        item = {"path": path, "available": bool(path)}
        if path and name == "ffmpeg":
            code, output = _probe([path, "-hide_banner", "-filters"])
            item.update({"probe_exit_code": code, "filters": parse_filters(output)})
            item["subtitle_burnin_ready"] = item["filters"]["subtitles"] or item["filters"]["ass"]
        if path and name == "tesseract":
            code, output = _probe([path, "--list-langs"])
            langs = [line.strip() for line in output.splitlines() if re.fullmatch(r"[A-Za-z0-9_+-]+", line.strip())]
            item.update({"probe_exit_code": code, "languages": langs, "chinese_ready": "chi_sim" in langs or "chi_tra" in langs})
        report["tools"][name] = item
    for name, value in config["files"].items():
        path = Path(value).expanduser()
        report["files"][name] = {"path": str(path) if value else None, "exists": bool(value) and path.exists()}
    # Inspect presence/size only. Never open secret files or print their paths/values.
    for name, value in config["secret_files"].items():
        path = Path(value).expanduser()
        report["secret_files"][name] = {"present_nonempty": bool(value) and path.is_file() and path.stat().st_size > 0}
    report["python"]["modules"] = {name: importlib.util.find_spec(name) is not None for name in ("PIL", "fitz", "pptx", "docx", "httpx")}
    if check_services:
        report["services"] = {name: local_health(url) for name, url in config["local_services"].items()}
    return report


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def confined(path, root):
    p = Path(path).expanduser().resolve()
    if not p.is_relative_to(root):
        raise ValueError("task write or evidence path is outside project root")
    return p


def valid_token(value):
    if not TOKEN.fullmatch(value) or value.lower().startswith(("sk-", "bearer", "api_key", "token=")):
        raise ValueError("invalid task identifier")
    return value


@contextlib.contextmanager
def ledger_transaction(path, root):
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project root is not a directory")
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise ValueError("ledger symlinks are not permitted")
    target = confined(raw, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    lockpath = target.with_name(target.name + ".lock")
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    deadline = time.monotonic() + 3
    while True:
        try:
            lockfd = os.open(lockpath, flags, 0o600)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError("ledger locked; inspect owner before removing stale lock") from None
            time.sleep(0.05)
    try:
        os.close(lockfd)
        data = json.loads(target.read_text()) if target.exists() else {"schema_version": 1, "project_root": str(root), "tasks": {}}
        if data.get("schema_version") != 1 or data.get("project_root") != str(root):
            raise ValueError("ledger schema or project root mismatch")
        yield data, root
        fd, tmp = tempfile.mkstemp(prefix=".runtime-ledger-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, indent=2)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    finally:
        lockpath.unlink()


def register(data, root, task_id, kind, request_file=None, outputs=(), max_attempts=2):
    valid_token(task_id)
    if task_id in data["tasks"]:
        raise ValueError("task already registered; inspect it instead of resubmitting")
    if kind not in KINDS or not 1 <= max_attempts <= 3:
        raise ValueError("invalid task kind or attempt budget")
    resolved = [str(confined(p, root)) for p in outputs]
    if any(Path(p).exists() for p in resolved):
        raise ValueError("output already exists; use a unique task output")
    task = {"id": task_id, "kind": kind, "status": "prepared", "attempts": 0, "max_attempts": max_attempts, "request_sha256": fingerprint(request_file) if request_file else None, "outputs": resolved, "external_id": None, "evidence": [], "history": [{"at": now(), "status": "prepared"}]}
    data["tasks"][task_id] = task
    return task


def transition(task, root, status, external_id=None, evidence=()):
    if status not in NEXT[task["status"]]:
        raise ValueError("invalid task state transition")
    if external_id:
        valid_token(external_id)
        if task["external_id"] and task["external_id"] != external_id:
            raise ValueError("remote task ID cannot be replaced")
    effective_id = external_id or task["external_id"]
    if status == "submitted" and not effective_id:
        raise ValueError("submitted requires the actual service task ID")
    if task["status"] == "prepared" and status in {"running", "submitted"}:
        if task["attempts"] >= task["max_attempts"]:
            raise ValueError("attempt budget exhausted")
    proof = [confined(p, root) for p in evidence]
    if status == "succeeded":
        output_paths = [confined(p, root) for p in task["outputs"]]
        if not output_paths or not proof or any(not p.is_file() or p.stat().st_size == 0 for p in [*output_paths, *proof]):
            raise ValueError("success requires nonempty outputs and evidence files")
    if task["status"] == "prepared" and status in {"running", "submitted"}:
        task["attempts"] += 1
    task["status"] = status
    task["external_id"] = effective_id
    task["evidence"].extend({"path": str(p), "sha256": fingerprint(p)} for p in proof)
    task["history"].append({"at": now(), "status": status})
    return task


def retry_plan(task):
    # A lost create response may already have incurred cost. Never advise another submit.
    if task["status"] in {"submitted", "running", "unknown"}:
        return {"action": "query_existing" if task["external_id"] else "reconcile_service_history", "may_retry": False}
    if task["status"] != "failed":
        return {"action": "none", "may_retry": False}
    if task["kind"] not in {"local-analysis", "local-render"}:
        return {"action": "review_failure_and_prepare_new_explicit_task", "may_retry": False}
    if task["attempts"] >= task["max_attempts"]:
        return {"action": "stop_budget_exhausted", "may_retry": False}
    return {"action": "retry_local_after_diagnosis", "may_retry": True, "remaining_attempts": task["max_attempts"] - task["attempts"], "backoff_seconds": min(30, 2 ** task["attempts"])}


def reset_for_retry(task):
    if not retry_plan(task)["may_retry"]:
        raise ValueError("retry is not safe or attempt budget is exhausted")
    if any(Path(p).exists() for p in task["outputs"]):
        raise ValueError("partial outputs exist; inspect and preserve before retry")
    task["status"] = "prepared"
    task["history"].append({"at": now(), "status": "prepared", "reason": "local_retry_after_diagnosis"})
    return task


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--config")
    d.add_argument("--check-local-services", action="store_true")
    for name in ("register", "status", "transition", "retry-plan", "retry"):
        p = sub.add_parser(name)
        p.add_argument("--project-root", required=True)
        p.add_argument("--ledger", required=True)
        p.add_argument("--id", required=True)
        if name == "register":
            p.add_argument("--kind", required=True, choices=KINDS)
            p.add_argument("--request-file")
            p.add_argument("--output", action="append", default=[])
            p.add_argument("--max-attempts", type=int, default=2)
        if name == "transition":
            p.add_argument("--to", required=True, choices=STATES)
            p.add_argument("--external-id")
            p.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(load_config(args.config), args.check_local_services)
        else:
            with ledger_transaction(args.ledger, args.project_root) as (data, root):
                if args.command == "register":
                    result = register(data, root, args.id, args.kind, args.request_file, args.output, args.max_attempts)
                else:
                    valid_token(args.id)
                    task = data["tasks"][args.id]
                    if args.command == "status": result = task
                    elif args.command == "transition": result = transition(task, root, args.to, args.external_id, args.evidence)
                    elif args.command == "retry-plan": result = retry_plan(task)
                    else: result = reset_for_retry(task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
        # Exception messages can contain secrets from malicious file names/configs.
        print(json.dumps({"error": "runtime operation rejected; check arguments, file permissions, state transition, and task budget"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
