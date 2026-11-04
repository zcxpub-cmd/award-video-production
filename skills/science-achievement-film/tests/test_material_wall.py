"""Offline integration and security tests. Run: python3 -m unittest discover -s tests."""
import argparse
import csv
import http.client
import importlib.util
import io
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "material_wall.py"
spec = importlib.util.spec_from_file_location("material_wall", SCRIPT)
wall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wall)


class WallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "clip.mp4"
        self.source.write_bytes(b"0123456789abcdef")
        self.input = self.root / "assets.json"
        self.data = {"title": "示例成果", "assets": [{"asset_id": "A01", "chapter_id": "C01", "source_path": "clip.mp4", "origin": "单位提交", "local_codex_generated": False, "display_ai_badge": True, "sentence_ids": ["C01_S01"], "semantic_reason": "展示完整装置", "review_status": "pending", "review_note": ""}, {"asset_id": "A02", "chapter_id": "C02", "source_path": "missing.mp4", "origin": "AI 候选外部提交", "local_codex_generated": True}]}
        self.input.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        self.output = self.root / "wall"
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(2)
        self.temp.cleanup()

    def build(self, copy=False, thumbnails=False, proxies=False, proxy_audio="keep"):
        return wall.build(argparse.Namespace(input=str(self.input), output=str(self.output), copy_media=copy, thumbnails=thumbnails, proxies=proxies, proxy_audio=proxy_audio))

    def start(self):
        self.build()
        self.server = wall.make_server(self.output)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, method="GET", data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        body = json.dumps(data).encode() if data is not None else None
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def post_headers(self):
        return {"Origin": self.origin, "X-Wall-Token": self.server.wall_state.token, "Content-Type": "application/json"}

    def test_homepage_and_wall_have_distinct_routes(self):
        self.start()
        status, headers, home = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn(b'./home.css', home)
        self.assertIn(b'id="enter-wall"', home)
        self.assertEqual(self.request("/index.html")[2], home)
        self.assertEqual((self.output / "index.html").read_bytes(), home)
        self.assertIn(b'id="wall-title"', self.request("/wall.html")[2])

    def test_homepage_also_opens_legacy_wall(self):
        self.start()
        legacy = (self.output / "wall.html").read_bytes()
        (self.output / "wall.html").replace(self.output / "index.html")
        status, _, page = self.request("/wall.html")
        self.assertEqual(status, 200)
        self.assertEqual(page, legacy)
        self.assertIn(b'id="enter-wall"', self.request("/")[2])

    def test_build_outputs_and_ai_rule(self):
        result = self.build()
        self.assertEqual(result["asset_count"], 2)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertFalse(manifest["assets"][0]["display_ai_badge"])
        self.assertTrue(manifest["assets"][1]["display_ai_badge"])
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(self.source.read_bytes(), b"0123456789abcdef")
        self.assertTrue((self.output / "app.js").is_file())
        self.assertTrue(manifest["assets"][1]["issues"])

    def test_copy_media_is_portable(self):
        self.build(copy=True)
        self.source.unlink()
        moved = self.root / "moved"
        self.output.rename(moved)
        state = wall.WallState(moved)
        with state.open_media("/media/A01/source")[0] as handle:
            self.assertEqual(handle.read(), b"0123456789abcdef")

    def test_existing_output_never_overwritten(self):
        self.build()
        before = (self.output / "reviews.json").read_bytes()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.output / "reviews.json").read_bytes(), before)

    def test_csv_input_existing_headers_and_boolean_parsing(self):
        self.input = self.root / "assets.csv"
        with self.input.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=wall.CSV_FIELDS)
            writer.writeheader()
            writer.writerow({"asset_id": "C01", "source_path": "clip.mp4", "local_codex_generated": "false", "display_ai_badge": "true", "sentence_ids": "S01|S02", "review_status": "通过"})
        self.build()
        asset = json.loads((self.output / "manifest.json").read_text())["assets"][0]
        self.assertFalse(asset["display_ai_badge"])
        self.assertEqual(asset["sentence_ids"], ["S01", "S02"])
        self.assertEqual(asset["review_status"], "approved")

    def test_reject_ids_urls_and_duplicate_ids(self):
        for value in ["../bad", "bad/id", "", "<script>"]:
            self.data["assets"][0]["asset_id"] = value
            self.input.write_text(json.dumps(self.data))
            with self.assertRaises(ValueError):
                self.build()
            self.assertFalse(self.output.exists())
        self.data["assets"][0]["asset_id"] = "A02"
        self.input.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            self.build()
        self.data["assets"][0]["asset_id"] = "A01"
        self.data["assets"][0]["source_path"] = "https://example.invalid/a.mp4"
        self.input.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            self.build()

    def test_missing_ffmpeg_reports_and_continues(self):
        with mock.patch.object(wall.shutil, "which", return_value=None):
            result = self.build(thumbnails=True)
        self.assertIn("ffmpeg", result["warnings"][0])

    def test_api_roundtrip_persists_and_exports(self):
        self.start()
        status, _, session = self.request("/api/session")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(session)["csrf_token"], self.server.wall_state.token)
        payload = {"asset_id": "A01", "review_status": "approved", "review_note": "=保留科学标签，核实装置全貌"}
        status, _, body = self.request("/api/reviews", "POST", payload, self.post_headers())
        self.assertEqual(status, 200, body)
        state = wall.WallState(self.output)
        self.assertEqual(state.reviews["assets"]["A01"]["review_status"], "approved")
        self.assertNotEqual(state.token, self.server.wall_state.token)
        status, headers, data = self.request("/api/export?format=json")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(json.loads(data)["assets"][0]["review_note"], payload["review_note"])
        status, _, data = self.request("/api/export?format=csv")
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["review_status"], "approved")
        self.assertTrue(rows[0]["review_note"].startswith("'="))
        self.assertTrue(json.loads(self.input.read_text())["assets"][0]["display_ai_badge"])
        self.assertEqual(json.loads(self.input.read_text())["assets"][0]["review_status"], "pending")

    def test_media_range_get_and_head(self):
        self.start()
        for requested, expected, content_range in [("bytes=2-5", b"2345", "bytes 2-5/16"), ("bytes=14-", b"ef", "bytes 14-15/16"), ("bytes=-3", b"def", "bytes 13-15/16"), ("bytes=0-99", b"0123456789abcdef", "bytes 0-15/16")]:
            status, headers, data = self.request("/media/A01/source", headers={"Range": requested})
            self.assertEqual(status, 206)
            self.assertEqual(data, expected)
            self.assertEqual(headers["Content-Range"], content_range)
        status, headers, data = self.request("/media/A01/source", "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"")
        self.assertEqual(headers["Content-Length"], "16")
        for requested in ["bytes=100-", "bytes=7-2", "bytes=-0", "bytes=0-1,4-6", "none"]:
            status, headers, _ = self.request("/media/A01/source", headers={"Range": requested})
            self.assertEqual(status, 416)
            self.assertEqual(headers["Content-Range"], "bytes */16")

    def test_paths_and_private_files_are_not_served(self):
        self.start()
        for path in ["/media-map.json", "/records.json", "/reviews.json", "/manifest.json", "/../assets.json", "/%2e%2e/assets.json", "/media/A01/../../assets.json", "/media/A01/source/", "/media/A01/%2e%2e", "/etc/passwd", "/media/A01/source%00"]:
            self.assertEqual(self.request(path)[0], 404, path)
        status, headers, _ = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_cross_origin_csrf_host_and_bad_ids_rejected(self):
        self.start()
        payload = {"asset_id": "A01", "review_status": "rejected", "review_note": ""}
        for headers in [{}, {**self.post_headers(), "Origin": "https://attacker.invalid"}, {**self.post_headers(), "X-Wall-Token": "incorrect"}, {**self.post_headers(), "Sec-Fetch-Site": "cross-site"}, {**self.post_headers(), "Host": "attacker.invalid"}]:
            self.assertEqual(self.request("/api/reviews", "POST", payload, headers)[0], 403)
        self.assertEqual(self.request("/api/session", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/session", headers={"Origin": "https://attacker.invalid"})[0], 403)
        for bad in [{**payload, "asset_id": "../oops"}, {**payload, "asset_id": "unknown"}, {**payload, "review_status": "deleted"}, {**payload, "review_note": "x" * 10001}, {**payload, "extra": "field"}, {**payload, "review_status": []}]:
            self.assertEqual(self.request("/api/reviews", "POST", bad, self.post_headers())[0], 400)
        self.assertEqual(self.server.wall_state.reviews["assets"]["A01"]["review_status"], "pending")

    def test_replaced_source_and_symlink_are_rejected(self):
        self.start()
        self.source.unlink()
        self.source.symlink_to(self.input)
        self.assertEqual(self.request("/media/A01/source")[0], 404)
        self.source.unlink()
        other = self.root / "other.mp4"
        other.write_bytes(b"private unrelated file")
        other.replace(self.source)
        self.assertEqual(self.request("/media/A01/source")[0], 404)

    def test_portable_media_cannot_escape_package(self):
        self.build(copy=True)
        state = wall.WallState(self.output)
        state.media_map["/media/A01/source"]["path"] = "../clip.mp4"
        with self.assertRaises(ValueError):
            state.open_media("/media/A01/source")
        state.media_map["/media/A01/source"]["path"] = "media/A01-source.mp4"
        target = self.output / "media" / "A01-source.mp4"
        target.unlink()
        target.symlink_to(self.source)
        with self.assertRaises(ValueError):
            state.open_media("/media/A01/source")

    def test_review_symlink_does_not_overwrite_target(self):
        self.start()
        target = self.output / "reviews.json"
        target.unlink()
        target.symlink_to(self.input)
        before = self.input.read_bytes()
        self.assertEqual(self.request("/api/reviews", "POST", {"asset_id": "A01", "review_status": "approved", "review_note": ""}, self.post_headers())[0], 400)
        self.assertEqual(before, self.input.read_bytes())

    def test_cli_help_and_build(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        result = subprocess.run([sys.executable, str(SCRIPT), "build", str(self.input), "--output", str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["asset_count"], 2)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local ffmpeg / ffprobe required for real proxy fixture")
    def test_real_avi_proxy_streams_duration_audio_and_source_preserved(self):
        source = self.root / "legacy.avi"
        result = subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=8", "-f", "lavfi", "-i", "sine=frequency=420:sample_rate=16000", "-t", "1", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(source)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.data["assets"] = [dict(self.data["assets"][0], source_path="legacy.avi")]
        self.input.write_text(json.dumps(self.data))
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        self.build(proxies=True, thumbnails=True)
        asset = json.loads((self.output / "manifest.json").read_text())["assets"][0]
        self.assertEqual(asset["preview_status"], "generated", asset["issues"])
        self.assertTrue((self.output / "media" / "A01-thumbnail.jpg").stat().st_size)
        proxy = self.output / "media" / "A01-preview.mp4"
        probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(proxy)], capture_output=True, text=True, timeout=10)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        streams = json.loads(probe.stdout)
        video = next(s for s in streams["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["codec_name"], video["width"], video["height"]), ("h264", 96, 64))
        self.assertTrue(any(s["codec_name"] == "aac" for s in streams["streams"]))
        self.assertAlmostEqual(float(streams["format"]["duration"]), 1, delta=.15)
        decoded = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(proxy), "-f", "null", "-"], capture_output=True, timeout=30)
        self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        self.output = self.root / "wall-mute"
        self.build(proxies=True, proxy_audio="mute")
        probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "json", str(self.output / "media" / "A01-preview.mp4")], capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(probe.stdout)["streams"], [])
        self.data["assets"][0]["preview_path"] = "wall/media/A01-preview.mp4"
        self.input.write_text(json.dumps(self.data))
        self.output = self.root / "wall-reuse"
        with mock.patch.object(wall, "generate_proxy", side_effect=AssertionError("must reuse existing preview")):
            self.build(proxies=True)
        self.assertEqual(json.loads((self.output / "manifest.json").read_text())["assets"][0]["preview_status"], "provided")

    def test_proxy_failure_visible_and_source_untouched(self):
        before = self.source.read_bytes()
        with mock.patch.object(wall.shutil, "which", return_value=None):
            result = self.build(proxies=True)
        asset = json.loads((self.output / "manifest.json").read_text())["assets"][0]
        self.assertEqual(asset["preview_status"], "failed")
        self.assertTrue(any("代理生成失败" in issue for issue in asset["issues"]))
        self.assertTrue(result["warnings"])
        self.assertEqual(before, self.source.read_bytes())


if __name__ == "__main__":
    unittest.main()
