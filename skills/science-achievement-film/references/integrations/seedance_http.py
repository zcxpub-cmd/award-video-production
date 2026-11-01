#!/usr/bin/env python3
"""Original minimal Ark task client. No automatic retries, models, or paid tests.

Implements the HTTP field contract; contains no upstream implementation code.
Request JSON is supplied by the caller and must not contain API credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
TASK_PATH = "/api/v3/contents/generations/tasks"
# Exact provider output hosts documented by the public Ark/LAS task APIs.
# No wildcard trust, custom proxy, private-IP fallback, or redirect is allowed.
DOWNLOAD_HOSTS = frozenset({
    "ark-content-generation-cn-beijing.tos-cn-beijing.volces.com",
    "ark-acg-cn-beijing.tos-cn-beijing.volces.com",
})


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual message echoes unknown arguments, potentially secrets.
        self.exit(2, "invalid arguments; use --help for accepted fields\n")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def endpoint(base):
    parsed = urlsplit(base)
    if (base != API_BASE and base != API_BASE + "/") or parsed.netloc != "ark.cn-beijing.volces.com":
        raise ValueError("only the approved official Ark API base is supported")
    return API_BASE + "/contents/generations/tasks"


def validate_api_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "ark.cn-beijing.volces.com"
            or parsed.query or parsed.fragment
            or not re.fullmatch(re.escape(TASK_PATH) + r"(?:/[A-Za-z0-9_-]{1,128})?", parsed.path)):
        raise ValueError("unapproved authenticated API URL")


def validate_download_url(url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url):
        raise ValueError("invalid download URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in DOWNLOAD_HOSTS
            or parsed.fragment or not parsed.path or parsed.path == "/"):
        raise ValueError("unapproved provider download host")


def validate_request(data):
    fields = {"model", "content", "ratio", "duration", "resolution", "seed", "camera_fixed", "watermark", "generate_audio"}
    if not isinstance(data, dict) or set(data) - fields or not isinstance(data.get("model"), str) or not data["model"].strip():
        raise ValueError("invalid task fields or model")
    content = data.get("content")
    if not isinstance(content, list) or not content or len(content) > 16:
        raise ValueError("content required")
    for item in content:
        if not isinstance(item, dict):
            raise ValueError("invalid content")
        if item.get("type") == "text":
            if set(item) != {"type", "text"} or not isinstance(item["text"], str) or not item["text"].strip():
                raise ValueError("text content required")
        elif item.get("type") in {"image_url", "video_url", "audio_url"}:
            field = item["type"]
            roles = {"image_url": {"first_frame", "last_frame", "reference_image"}, "video_url": {"reference_video"}, "audio_url": {"reference_audio"}}
            if set(item) != {"type", field, "role"} or item["role"] not in roles[field] or set(item[field]) != {"url"}:
                raise ValueError("invalid reference role")
            url = item[field]["url"]
            if not isinstance(url, str) or not url.startswith(("https://", "data:")):
                raise ValueError("reference must be HTTPS or data URL")
        else:
            raise ValueError("unsupported content type")
    return data


def atomic_save(path, data):
    fd, temp = tempfile.mkstemp(prefix=".task-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def send(url, key, payload=None):
    # Never return or log headers, response body on failure, or signed video URLs.
    validate_api_url(url)  # Enforce again here, even when called outside main().
    request = Request(url, data=payload, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=60) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024: raise ValueError("oversized service response")
        return json.loads(raw)


def download(url, destination):
    validate_download_url(url)
    partial = destination.with_name(destination.name + ".part")
    if destination.exists() or destination.is_symlink(): raise ValueError("output exists")
    # Exclusive partial creation preserves existing candidates on every failure.
    with partial.open("xb") as out:
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=60) as response:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 1024 ** 3: raise ValueError("download size exceeds 1 GiB")
                out.write(chunk)
    if count == 0: raise ValueError("empty download")
    # Link exclusively rather than replacing a concurrently created destination.
    os.link(partial, destination)
    partial.unlink()


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "submit", "query"])
    parser.add_argument("--request")
    parser.add_argument("--journal")
    parser.add_argument("--key-file")
    parser.add_argument("--base-url")
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--download")
    args = parser.parse_args(argv)
    journal = None
    record = None
    lock = None
    try:
        payload = None
        if args.action in {"validate", "submit"}:
            request_path = Path(args.request)
            if request_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("request exceeds 32 MiB")
            data = validate_request(json.loads(request_path.read_text(encoding="utf-8")))
            payload = json.dumps(data, ensure_ascii=False).encode()
        if args.action == "validate":
            print(json.dumps({"valid": True, "request_sha256": hashlib.sha256(payload).hexdigest(), "network_called": False}))
            return 0
        if not args.journal or not args.key_file or not args.base_url:
            raise ValueError("explicit journal, key file, and API base required")
        if args.action == "submit" and not args.allow_billable:
            raise ValueError("billable action must be explicitly selected")
        api = endpoint(args.base_url)
        key = Path(args.key_file).read_text(encoding="utf-8").strip()
        if not key or "\n" in key or "\r" in key: raise ValueError("invalid key")
        journal = Path(args.journal)
        if journal.is_symlink(): raise ValueError("journal symlink refused")
        lock = journal.with_name(journal.name + ".lock")
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        if args.action == "submit":
            if journal.exists(): raise ValueError("already registered; query or reconcile existing task")
            record = {"request_sha256": hashlib.sha256(payload).hexdigest(), "endpoint_sha256": hashlib.sha256(api.encode()).hexdigest(), "status": "unknown", "task_id": None}
            atomic_save(journal, record)  # Persist uncertainty BEFORE a potentially billable POST.
            response = send(api, key, payload)
            task_id = response.get("id")
            if not isinstance(task_id, str) or task_id == key or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                raise ValueError("missing task ID; reconcile service history")
            record.update(status="submitted", task_id=task_id)
        else:
            record = json.loads(journal.read_text())
            if record.get("endpoint_sha256") != hashlib.sha256(api.encode()).hexdigest():
                raise ValueError("query endpoint does not match original submission")
            task_id = record.get("task_id")
            if not isinstance(task_id, str) or task_id == key or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
                raise ValueError("unknown remote task; reconcile service history")
            response = send(api + "/" + task_id, key)
            status = response.get("status")
            record["status"] = status if status in {"queued", "running", "succeeded", "failed", "cancelled", "expired"} else "unknown"
            if args.download:
                if status != "succeeded": raise ValueError("task not completed")
                video_url = response["content"]["video_url"]
                if not isinstance(video_url, str) or key in video_url:
                    raise ValueError("unsafe download URL")
                download(video_url, Path(args.download))
                record["downloaded"] = True
        atomic_save(journal, record)
        print(json.dumps({"status": record["status"], "task_id": record["task_id"], "downloaded": record.get("downloaded", False)}))
        return 0
    except Exception:
        # Do not stringify unexpected library/service errors: they can embed URLs or keys.
        print(json.dumps({"error": "operation failed; preserve journal, inspect local configuration, and query existing task; never blindly resubmit"}))
        return 2
    finally:
        if lock is not None:
            # Only the current process's successfully acquired lock may be removed.
            if 'fd' in locals() and lock.exists(): lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
