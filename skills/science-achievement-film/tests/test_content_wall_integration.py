"""Forward CLI contract: handwritten manuscript -> handoff -> portable wall.

All inputs are synthetic and created under a temporary directory. No fixtures,
private paths, accounts, network calls, models, or third-party libraries.
"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class ContentWallIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="film-forward-contract-")
        self.root = Path(self.temp.name)
        for folder in ("story", "media files", "delivery/phase1"):
            (self.root / folder).mkdir(parents=True)
        for name in ("source.wav", "preview.wav"):
            with wave.open(str(self.root / "media files" / name), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 800)
        # A valid one-pixel PNG serves as an explicitly supplied thumbnail.
        (self.root / "media files/thumb.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/L9sAAAAASUVORK5CYII="))
        self.manuscript = {"project_title": "虚构成果演示", "chapters": [{"chapter_id": "C01", "title": "示例章节", "units": ["示例研究单位"], "sentences": [{"id": "C01_S01", "text": "用于接口验证的虚构说明。"}]}]}
        self.shots = {"shots": [{"asset_id": "A01", "chapter_id": "C01", "source_path": "../media files/source.wav", "preview_path": "../media files/preview.wav", "thumbnail_path": "../media files/thumb.png", "sentence_ids": ["C01_S01"], "semantic_reason": "测试跨目录交接及媒体路径保持", "origin": "虚构测试源", "local_codex_generated": False, "source_in_s": 0, "source_out_s": 0.1}]}
        self.manuscript_path = self.root / "story/manuscript.json"
        self.shots_path = self.root / "story/shots.json"
        self.output = self.root / "delivery/phase1/wall-input.json"
        self.manuscript_path.write_text(json.dumps(self.manuscript, ensure_ascii=False), encoding="utf-8")
        self.write_shots()

    def tearDown(self):
        self.temp.cleanup()

    def write_shots(self):
        self.shots_path.write_text(json.dumps(self.shots, ensure_ascii=False), encoding="utf-8")

    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=20)

    def handoff(self):
        return self.run_cli("content_tools.py", "handoff", self.manuscript_path, self.shots_path, "--out", self.output)

    def wall(self):
        return self.run_cli("material_wall.py", "build", self.output, "--output", self.root / "wall", "--copy-media")

    def test_cross_directory_handoff_preserves_source_preview_thumbnail(self):
        originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "media files").iterdir()}
        handoff = self.handoff()
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        output = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(output["mapping_check"]["reference_structure_valid"])
        for key in ("source_path", "preview_path", "thumbnail_path"):
            path = Path(output["assets"][0][key])
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.is_file())
        built = self.wall()
        self.assertEqual(built.returncode, 0, built.stderr)
        manifest = json.loads((self.root / "wall/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["assets"][0]["media"]), {"source", "preview", "thumbnail"})
        self.assertEqual(manifest["assets"][0]["preview_status"], "provided")
        self.assertEqual(manifest["assets"][0]["issues"], [])
        self.assertTrue(manifest["portable"])
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "media files").iterdir()}
        self.assertEqual(originals, after)

    def test_eighty_character_asset_id_works_in_both_tools(self):
        self.shots["shots"][0]["asset_id"] = "A" + "0" * 79
        self.write_shots()
        handed = self.handoff()
        self.assertEqual(handed.returncode, 0, handed.stderr)
        built = self.wall()
        self.assertEqual(built.returncode, 0, built.stderr)

    def test_invalid_leading_id_rejected_before_handoff_output(self):
        for asset_id in ("_A01", "-A01"):
            self.shots["shots"][0]["asset_id"] = asset_id
            self.write_shots()
            handed = self.handoff()
            self.assertNotEqual(handed.returncode, 0)
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
