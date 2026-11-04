#!/usr/bin/env python3
"""Build and serve an offline material review wall. Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

VERSION = "1.0.0"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
STATUSES = {"pending", "approved", "rejected"}
STATUS_ALIASES = {"待审": "pending", "通过": "approved", "弃用": "rejected", "pass": "approved", "reject": "rejected"}
CSV_FIELDS = "asset_id,chapter_id,origin,local_codex_generated,display_ai_badge,source_path,source_version,availability,probe_status,watched_ranges,source_in_s,source_out_s,preview_path,sentence_ids,semantic_reason,resolution,text_policy,person_or_logo,duplicate_group,full_form_ending,review_status,review_note,license_evidence".split(",")
MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".mxf": "application/mxf", ".mts": "video/mp2t",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif", ".tif": "image/tiff", ".tiff": "image/tiff", ".heic": "image/heic", ".bmp": "image/bmp", ".exr": "image/x-exr",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg", ".aif": "audio/aiff", ".aiff": "audio/aiff",
}
TEMPLATES = Path(__file__).resolve().parent.parent / "assets/wall"
HOME_STATIC = {
    "/": ("home.html", "text/html; charset=utf-8"),
    "/index.html": ("home.html", "text/html; charset=utf-8"),
    "/home.css": ("home.css", "text/css; charset=utf-8"),
    "/home.js": ("home.js", "text/javascript; charset=utf-8"),
    "/cover-scenes.js": ("cover-scenes.js", "text/javascript; charset=utf-8"),
}
WALL_STATIC = {
    "/wall.html": ("wall.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
VIDEO_EXTENSIONS = {suffix for suffix, mime in MIME.items() if mime.startswith("video/")} | {".mxf"}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def bool_value(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"})


def sentence_ids(value):
    if isinstance(value, list):
        return [str(v) for v in value]
    if not value:
        return []
    if isinstance(value, str) and value.lstrip().startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("sentence_ids must be an array")
        return [str(v) for v in parsed]
    return [v for v in re.split(r"[|;,，；\s]+", str(value).strip()) if v]


def safe_file(path):
    """Do not hydrate cloud placeholders or follow a final symlink."""
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise ValueError(f"不读取符号链接文件：{path.name}")
    for item in [path, *path.parents]:
        info = item.lstat()
        if item.name.endswith(".icloud") or getattr(info, "st_flags", 0) & getattr(stat, "UF_DATALESS", 0x40000000):
            raise ValueError(f"文件尚未在本机完整可用：{item.name}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"不是普通文件：{path.name}")
    return resolved


def read_input(path):
    path = safe_file(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            if "asset_id" not in fields:
                raise ValueError("CSV 缺少 asset_id 列")
            rows = list(reader)
        return {"title": path.stem, "assets": rows}, fields
    with path.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError('输入 JSON 必须是 {"title": "…", "assets": [...]}')
    return data, CSV_FIELDS


def resolve_source(base, raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    if "://" in raw or raw.startswith("file:") or "\x00" in raw:
        raise ValueError("素材仅接受本地文件路径，不接受 URL")
    path = Path(raw).expanduser()
    return safe_file(path if path.is_absolute() else base / path)


def proxy_needed(path, ffprobe):
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt", "-of", "json", str(path)], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise ValueError("ffprobe 无法读取源视频流")
    streams = json.loads(result.stdout).get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        raise ValueError("源文件未探测到视频流")
    main = video[0]
    compatible_mp4 = path.suffix.lower() in {".mp4", ".m4v"} and main.get("codec_name") == "h264" and main.get("pix_fmt") in {"yuv420p", "yuvj420p"} and all(s.get("codec_name") in {"aac", "mp3"} for s in audio)
    compatible_webm = path.suffix.lower() == ".webm" and main.get("codec_name") in {"vp8", "vp9"} and main.get("pix_fmt") == "yuv420p" and all(s.get("codec_name") in {"opus", "vorbis"} for s in audio)
    return not (compatible_mp4 or compatible_webm)


def generate_proxy(source, target, ffmpeg, audio):
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-map", "0:v:0"]
    command += ["-an"] if audio == "mute" else ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]
    command += ["-vf", "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, capture_output=True, timeout=600)
    if result.returncode or not target.is_file() or not target.stat().st_size:
        raise ValueError("ffmpeg 代理转码失败（需本机 ffmpeg 支持 libx264 / AAC）")


def build(args):
    input_path = safe_file(Path(args.input).expanduser())
    data, csv_fields = read_input(input_path)
    destination = Path(args.output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("输出目录已存在；请换一个新目录，以免覆盖素材墙或审核记录")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".material-wall-", dir=destination.parent))
    warnings, assets, records, media_map = [], [], [], {}
    seen = set()
    proxy_requested = getattr(args, "proxies", False)
    proxy_audio = getattr(args, "proxy_audio", "keep")
    thumbnail_executable = shutil.which("ffmpeg") if args.thumbnails or proxy_requested else None
    probe_executable = shutil.which("ffprobe") if proxy_requested else None
    if args.thumbnails and not thumbnail_executable:
        warnings.append("未找到 ffmpeg；跳过视频缩略图生成。可直接播放视频，或提供 thumbnail_path。")
    if proxy_requested and (not thumbnail_executable or not probe_executable):
        warnings.append("代理生成需要本机 ffmpeg 和 ffprobe；缺失时跳过，不会自动安装。")
    try:
        (temporary / "media").mkdir()
        for filename in ("app.js", "style.css", "home.css", "home.js", "cover-scenes.js"):
            shutil.copyfile(TEMPLATES / filename, temporary / filename)
        shutil.copytree(TEMPLATES / "cover", temporary / "cover")
        shutil.copyfile(TEMPLATES / "home.html", temporary / "index.html")
        shutil.copyfile(TEMPLATES / "index.html", temporary / "wall.html")
        for original in data["assets"]:
            if not isinstance(original, dict):
                raise ValueError("每个素材记录必须是对象")
            asset_id = str(original.get("asset_id", ""))
            if not ID.fullmatch(asset_id) or asset_id in seen:
                raise ValueError(f"asset_id 非法或重复：{asset_id!r}")
            seen.add(asset_id)
            row = dict(original)
            row["asset_id"] = asset_id
            row["local_codex_generated"] = bool_value(row.get("local_codex_generated"))
            row["display_ai_badge"] = row["local_codex_generated"]
            row["sentence_ids"] = sentence_ids(row.get("sentence_ids"))
            review = str(row.get("review_status") or "pending")
            review = STATUS_ALIASES.get(review, review)
            if review not in STATUSES:
                warnings.append(f"{asset_id}：未知审核状态 {review!r}，按待审处理。")
                review = "pending"
            row["review_status"] = review
            row["review_note"] = str(row.get("review_note") or "")
            public = {k: v for k, v in row.items() if k not in {"source_path", "preview_path", "thumbnail_path"}}
            public["media"] = {}
            public["issues"] = []
            resolved = {}
            for role in ("source", "preview", "thumbnail"):
                raw = row.get(role + "_path")
                if not raw:
                    continue
                # Bad URL/path syntax is a manifest error; unavailable files stay visible.
                if not isinstance(raw, str) or "://" in raw or raw.startswith("file:") or "\x00" in raw:
                    raise ValueError(f"{asset_id}：{role}_path 必须是本地文件路径")
                public[role + "_label"] = Path(raw).name
                try:
                    path = resolve_source(input_path.parent, raw)
                    mime = MIME.get(path.suffix.lower())
                    if not mime or (role == "thumbnail" and not mime.startswith("image/")):
                        raise ValueError("格式不能直接用作安全媒体预览")
                    resolved[role] = path
                    if args.copy_media:
                        target = temporary / "media" / f"{asset_id}-{role}{path.suffix.lower()}"
                        shutil.copy2(path, target)
                        mapping = {"path": target.relative_to(temporary).as_posix(), "relative": True, "mime": mime}
                    else:
                        info = path.stat()
                        mapping = {"path": str(path), "relative": False, "mime": mime, "device": info.st_dev, "inode": info.st_ino}
                    key = f"/media/{asset_id}/{role}"
                    media_map[key] = mapping
                    public["media"][role] = {"url": key, "mime": mime}
                except (OSError, ValueError) as exc:
                    public["issues"].append(f"{role} 不可预览：文件缺失、格式不支持、链接或未完成本地下载（{type(exc).__name__}）。")
            if "source" not in public["media"]:
                public["issues"].append("原始素材缺失或不可读取；此卡片不代表素材已验收。")
            public["preview_status"] = "provided" if "preview" in resolved else "original_candidate"
            if proxy_requested and "preview" not in resolved and resolved.get("source") and resolved["source"].suffix.lower() in VIDEO_EXTENSIONS:
                proxy = temporary / "media" / f"{asset_id}-preview.mp4"
                try:
                    if not thumbnail_executable or not probe_executable:
                        raise ValueError("缺少 ffmpeg 或 ffprobe，未生成代理")
                    if proxy_needed(resolved["source"], probe_executable):
                        generate_proxy(resolved["source"], proxy, thumbnail_executable, proxy_audio)
                        # Validate the output stream, while keeping browser acceptance separate.
                        if proxy_needed(proxy, probe_executable):
                            raise ValueError("代理输出不符合 H.264 / AAC 预览格式")
                        key = f"/media/{asset_id}/preview"
                        media_map[key] = {"path": proxy.relative_to(temporary).as_posix(), "relative": True, "mime": "video/mp4"}
                        public["media"]["preview"] = {"url": key, "mime": "video/mp4"}
                        public["preview_status"] = "generated"
                        public["preview_label"] = proxy.name
                        public["preview_preserves_timeline"] = True
                        public["proxy_audio"] = proxy_audio
                        resolved["preview"] = proxy
                    else:
                        public["preview_status"] = "original_candidate"
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    public["preview_status"] = "failed"
                    message = str(exc) if isinstance(exc, ValueError) else "转码超时或本机工具不可执行"
                    public["issues"].append(f"代理生成失败：{message}。原件未更改；尚无浏览器播放通过结论。")
                    proxy.unlink(missing_ok=True)
            if not public["media"]:
                public["preview_status"] = "unavailable"
            candidate = resolved.get("preview") or resolved.get("source")
            if args.thumbnails and thumbnail_executable and "thumbnail" not in public["media"] and candidate and candidate.suffix.lower() in VIDEO_EXTENSIONS:
                thumb = temporary / "media" / f"{asset_id}-thumbnail.jpg"
                try:
                    start = max(0.0, float(row.get("source_in_s") or 0)) if "preview" not in resolved or public.get("preview_preserves_timeline") else 0.0
                    result = subprocess.run([thumbnail_executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-ss", str(start), "-i", str(candidate), "-frames:v", "1", "-vf", "scale=640:360:force_original_aspect_ratio=decrease", str(thumb)], capture_output=True, timeout=90)
                    if result.returncode or not thumb.is_file() or not thumb.stat().st_size:
                        raise ValueError("ffmpeg 未生成可用缩略图")
                    key = f"/media/{asset_id}/thumbnail"
                    media_map[key] = {"path": thumb.relative_to(temporary).as_posix(), "relative": True, "mime": "image/jpeg"}
                    public["media"]["thumbnail"] = {"url": key, "mime": "image/jpeg"}
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    public["issues"].append("缩略图生成失败；原件未更改。")
                    thumb.unlink(missing_ok=True)
            row["preview_status"] = public["preview_status"]
            if public.get("preview_preserves_timeline"):
                row["preview_preserves_timeline"] = True
                row["proxy_audio"] = proxy_audio
            records.append(row)
            assets.append(public)
        manifest = {"version": VERSION, "title": str(data.get("title") or "影序素材墙"), "created_at": stamp(), "portable": bool(args.copy_media), "warnings": warnings, "assets": assets}
        write_json(temporary / "manifest.json", manifest)
        write_json(temporary / "records.json", {"title": manifest["title"], "csv_fields": list(dict.fromkeys([*csv_fields, *CSV_FIELDS, "thumbnail_path", "preview_status", "preview_preserves_timeline", "proxy_audio"])), "assets": records})
        write_json(temporary / "media-map.json", media_map)
        write_json(temporary / "reviews.json", {"version": 1, "updated_at": None, "assets": {a["asset_id"]: {"review_status": a["review_status"], "review_note": a["review_note"]} for a in assets}})
        (temporary / "START_HERE.txt").write_text("素材墙需要本机服务以保存审核并支持视频拖动。\n命令：python3 <插件目录>/scripts/material_wall.py serve \"<本素材墙目录>\" --port 8765\n浏览器打开 http://127.0.0.1:8765/ 。Ctrl+C 停止；下次重启审核记录仍保留。\n双击 index.html 只能看到启动说明，不能保存审核。\n" + ("此包已复制媒体，可整体迁移。\n" if args.copy_media else "此包引用本机原件，移动原件后须重新构建；需可移植包时构建时加 --copy-media。\n"), encoding="utf-8")
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {"ok": True, "output": str(destination), "asset_count": len(assets), "portable": bool(args.copy_media), "warnings": warnings}


def csv_cell(value):
    if isinstance(value, (list, dict)):
        result = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, bool):
        result = "true" if value else "false"
    else:
        result = "" if value is None else str(value)
    if result.lstrip().startswith(("=", "+", "-", "@")) or result.startswith(("\t", "\r", "\n")):
        result = "'" + result
    return result


class WallState:
    def __init__(self, directory):
        self.root = Path(directory).expanduser().resolve(strict=True)
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.manifest = self.read("manifest.json")
        self.records = self.read("records.json")
        self.media_map = self.read("media-map.json")
        self.ids = {a["asset_id"] for a in self.manifest["assets"]}
        if any(not ID.fullmatch(i) for i in self.ids):
            raise ValueError("素材墙包含非法 asset_id")
        self.reviews = self.read("reviews.json")
        if not isinstance(self.reviews.get("assets"), dict) or set(self.reviews["assets"]) != self.ids:
            raise ValueError("审核文件与素材清单不匹配")
        for item in self.reviews["assets"].values():
            if not isinstance(item, dict) or item.get("review_status") not in STATUSES or not isinstance(item.get("review_note"), str):
                raise ValueError("审核文件内容非法")
        for key, item in self.media_map.items():
            bits = key.split("/")
            if len(bits) != 4 or bits[:2] != ["", "media"] or bits[2] not in self.ids or bits[3] not in {"source", "preview", "thumbnail"} or item.get("mime") not in MIME.values():
                raise ValueError("媒体白名单格式非法")

    def read(self, name):
        path = self.root / name
        if path.is_symlink():
            raise ValueError(f"素材墙内部文件不能是符号链接：{name}")
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def update(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"asset_id", "review_status", "review_note"}:
            raise ValueError("审核请求必须只包含 asset_id、review_status、review_note")
        asset_id = payload["asset_id"]
        if not isinstance(asset_id, str) or not ID.fullmatch(asset_id) or asset_id not in self.ids:
            raise ValueError("非法 asset_id")
        if payload["review_status"] not in STATUSES:
            raise ValueError("非法审核状态")
        if not isinstance(payload["review_note"], str) or len(payload["review_note"]) > 10000:
            raise ValueError("备注必须是 10000 字以内文本")
        with self.lock:
            path = self.root / "reviews.json"
            if path.is_symlink():
                raise ValueError("审核文件不能是符号链接")
            updated = {"version": 1, "updated_at": stamp(), "assets": dict(self.reviews["assets"])}
            updated["assets"][asset_id] = {"review_status": payload["review_status"], "review_note": payload["review_note"]}
            fd, temporary = tempfile.mkstemp(prefix=".reviews-", suffix=".json", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(updated, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.reviews = updated
            return updated["assets"][asset_id]

    def exported(self):
        with self.lock:
            rows = [{**a, **self.reviews["assets"][a["asset_id"]]} for a in self.records["assets"]]
            # Exported JSON may be downloaded to another directory. Make media paths
            # unambiguous for that file; this private inventory is not the UI manifest.
            for row in rows:
                for role in ("source", "preview", "thumbnail"):
                    mapping = self.media_map.get(f"/media/{row['asset_id']}/{role}")
                    if mapping:
                        path = Path(mapping["path"])
                        row[role + "_path"] = str((self.root / path).resolve()) if mapping.get("relative") else str(path)
            return {"title": self.records["title"], "exported_at": stamp(), "assets": rows}

    def open_media(self, key):
        mapping = self.media_map[key]
        path = Path(mapping["path"])
        if mapping.get("relative"):
            path = self.root / path
            if path.is_symlink() or not path.resolve().is_relative_to(self.root / "media"):
                raise ValueError("媒体路径越界")
        elif not path.is_absolute():
            raise ValueError("外部媒体路径必须为绝对路径")
        safe_file(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        handle = os.fdopen(fd, "rb")
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or (not mapping.get("relative") and (info.st_dev != mapping.get("device") or info.st_ino != mapping.get("inode"))):
            handle.close()
            raise ValueError("原件被替换，请重新构建清单")
        return handle, info.st_size, mapping["mime"]


def range_bounds(value, size):
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()) or size == 0:
        raise ValueError("unsupported range")
    first, last = match.groups()
    if not first:
        count = int(last)
        if count <= 0:
            raise ValueError("invalid suffix")
        return max(0, size - count), size - 1, True
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("range outside file")
    return start, end, True


class WallHandler(BaseHTTPRequestHandler):
    server_version = "MaterialWall/2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Avoid control characters or private filenames in access logs.
        return

    @property
    def state(self):
        return self.server.wall_state

    def headers_safe(self):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        return (not origin or origin == "http://" + host) and self.headers.get("Sec-Fetch-Site") != "cross-site"

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Cache-Control", "no-store")

    def reply(self, status, data, content_type="application/json; charset=utf-8", extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def error(self, code, message):
        self.reply(code, {"error": message})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.headers_safe():
            self.error(403, "仅允许同源本机访问")
            return
        parsed = urlsplit(self.path)
        route = unquote(parsed.path)
        try:
            if route in HOME_STATIC:
                filename, mime = HOME_STATIC[route]
                self.reply(200, (TEMPLATES / filename).read_bytes(), mime)
            elif re.fullmatch(r"/cover/[a-z]+\.(mp4|webp)", route):
                cover = TEMPLATES / "cover"
                path = cover / route.rsplit("/", 1)[1]
                if cover.is_symlink() or path.is_symlink():
                    raise ValueError("首页媒体不能是符号链接")
                with path.open("rb") as handle:
                    self.stream_media(handle, path.stat().st_size, MIME[path.suffix])
            elif route in WALL_STATIC:
                filename, mime = WALL_STATIC[route]
                path = self.state.root / filename
                if filename == "wall.html" and not path.exists() and not path.is_symlink():
                    path = self.state.root / "index.html"  # Wall directories built before the homepage.
                if path.is_symlink():
                    raise ValueError("页面文件不能是符号链接")
                self.reply(200, path.read_bytes(), mime)
            elif route == "/api/session":
                self.reply(200, {"csrf_token": self.state.token})
            elif route == "/api/assets":
                self.reply(200, self.state.manifest)
            elif route == "/api/reviews":
                with self.state.lock:
                    self.reply(200, self.state.reviews)
            elif route == "/api/export":
                fmt = parse_qs(parsed.query).get("format", ["json"])[0]
                exported = self.state.exported()
                if fmt == "json":
                    self.reply(200, exported, extra={"Content-Disposition": 'attachment; filename="material-wall-review.json"'})
                elif fmt == "csv":
                    buffer = io.StringIO(newline="")
                    fields = self.state.records["csv_fields"]
                    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows({k: csv_cell(v) for k, v in row.items()} for row in exported["assets"])
                    self.reply(200, b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="material-wall-review.csv"'})
                else:
                    self.error(400, "format 仅接受 json 或 csv")
            elif route in self.state.media_map:
                self.media(route)
            else:
                self.error(404, "未找到；仅开放清单内媒体和固定页面")
        except (ValueError, OSError, KeyError):
            self.error(404, "文件不可读取或已变化，请重新构建素材墙")

    def media(self, route):
        handle, size, mime = self.state.open_media(route)
        with handle:
            self.stream_media(handle, size, mime)

    def stream_media(self, handle, size, mime):
        try:
            start, end, partial = range_bounds(self.headers.get("Range"), size)
        except ValueError:
            self.reply(416, b"", extra={"Content-Range": f"bytes */{size}"})
            return
        length = max(0, end - start + 1)
        self.send_response(206 if partial else 200)
        self.security_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        handle.seek(start)
        try:
            while length:
                chunk = handle.read(min(256 * 1024, length))
                if not chunk:
                    break
                self.wfile.write(chunk)
                length -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self.headers_safe() or self.headers.get("Origin") != "http://" + self.headers.get("Host", "") or not secrets.compare_digest(self.headers.get("X-Wall-Token", ""), self.state.token):
            self.close_connection = True
            self.error(403, "写入需要同源页面和本次启动令牌，请刷新页面")
            return
        if self.path != "/api/reviews":
            self.close_connection = True
            self.error(404, "未知写入接口")
            return
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or not 0 < int(length) <= 65536 or self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self.error(413, "请求体大小非法")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.close_connection = True
            self.error(415, "仅接受 application/json")
            return
        try:
            payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
            result = self.state.update(payload)
            self.reply(200, {"ok": True, "review": result})
        except (ValueError, TypeError, UnicodeDecodeError):
            self.error(400, "审核数据非法：请检查素材 ID、状态和备注")
        except OSError:
            self.error(500, "审核保存失败；请检查目录写入权限和磁盘空间")


def make_server(directory, port=0):
    state = WallState(directory)
    server = ThreadingHTTPServer(("127.0.0.1", port), WallHandler)
    server.daemon_threads = True
    server.wall_state = state
    return server


def serve(args):
    server = make_server(args.directory, args.port)
    home = f"http://127.0.0.1:{server.server_port}/"
    print(f"影序首页：{home}\n进入素材墙后可审核。记录保存在 {server.wall_state.root / 'reviews.json'}\n按 Ctrl+C 停止。", flush=True)
    try:
        if args.open_browser:
            threading.Thread(target=webbrowser.open, args=(home,), daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="影序素材墙：本地构建、播放、筛选、审核与导出。Python 标准库，无网络依赖。")
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="从 JSON / CSV 生成新素材墙目录，不覆盖输入和已有墙")
    builder.add_argument("input", help="素材 JSON 或 CSV；相对素材路径按此文件目录解析")
    builder.add_argument("--output", "--out", required=True, help="新的输出目录")
    builder.add_argument("--copy-media", action="store_true", help="复制清单内媒体，使输出目录可整体迁移（大素材需相应磁盘空间）")
    builder.add_argument("--thumbnails", action="store_true", help="使用本机 ffmpeg 提取视频缩略图，缺失时继续构建并提示")
    builder.add_argument("--proxies", action="store_true", help="明确允许用 ffprobe / ffmpeg 对不兼容候选生成完整视场 H.264 代理；已有 preview_path 优先复用")
    builder.add_argument("--proxy-audio", choices=("keep", "mute"), default="keep", help="新生成代理保留原音（keep，默认）或静音（mute）；原件始终保留")
    builder.set_defaults(func=build)
    server = commands.add_parser("serve", help="仅在 127.0.0.1 启动本机审核服务，Ctrl+C 停止")
    server.add_argument("directory", help="build 生成的素材墙目录")
    server.add_argument("--port", type=int, default=8765, help="本机端口（默认 8765，0 自动分配）")
    server.add_argument("--open", dest="open_browser", action="store_true", help="启动后用默认浏览器打开影序首页")
    server.set_defaults(func=serve)
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
