"""Offline demo regression: fictional inputs only, no GUI/server/network/model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/demo_project.py"
spec = importlib.util.spec_from_file_location("demo_project", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def executable_pair():
    options = [(os.environ.get("DEMO_TEST_FFMPEG"), os.environ.get("DEMO_TEST_FFPROBE")), (shutil.which("ffmpeg"), shutil.which("ffprobe")), ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe")]
    for ffmpeg, ffprobe in options:
        if not ffmpeg or not ffprobe or not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
            continue
        try:
            args = argparse.Namespace(ffmpeg=ffmpeg, ffprobe=ffprobe, font="sans-serif")
            demo.preflight(args, SCRIPT.parent)
            return ffmpeg, ffprobe
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


class DemoProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-demo-test-")
        self.root = Path(self.temp.name)
        self.out = self.root / "演示 project"
        self.args = argparse.Namespace(output=str(self.out), ffmpeg="ffmpeg", ffprobe="ffprobe", font="sans-serif")

    def tearDown(self):
        self.temp.cleanup()

    def test_help_documents_dependencies_and_boundaries(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--font", result.stdout)
        self.assertIn("libass", result.stdout)
        self.assertIn("不会启动服务", result.stdout)

    def test_existing_output_refused_without_modification(self):
        self.out.mkdir()
        marker = self.out / "keep.txt"
        marker.write_text("existing user artifact", encoding="utf-8")
        with mock.patch.object(demo, "preflight", side_effect=AssertionError("should refuse before dependencies")):
            with self.assertRaises(demo.DemoError):
                demo.demo(self.args)
        self.assertEqual(marker.read_text(), "existing user artifact")
        self.assertEqual(list(self.out.iterdir()), [marker])

    def test_missing_dependency_and_libass_do_not_create_project(self):
        with mock.patch.object(demo.shutil, "which", return_value=None):
            with self.assertRaisesRegex(demo.DemoError, "不会自动安装"):
                demo.demo(self.args)
        self.assertFalse(self.out.exists())
        fake = subprocess.CompletedProcess(["ffmpeg"], 0, " T.. blackdetect V->V detect\n ... testsrc2 |->V source\n", "")
        with mock.patch.object(demo.shutil, "which", side_effect=lambda name: name), mock.patch.object(demo, "run_process", return_value=fake):
            with self.assertRaisesRegex(demo.DemoError, "libass"):
                demo.demo(self.args)
        self.assertFalse(self.out.exists())

    def test_failed_stage_records_partial_state_not_success(self):
        with mock.patch.object(demo, "preflight", return_value=("ffmpeg", "ffprobe")), mock.patch.object(demo, "run_stage", side_effect=demo.DemoError("controlled fixture failure")):
            with self.assertRaises(demo.DemoError):
                demo.demo(self.args)
        failure = json.loads((self.out / "demo-failed.json").read_text())
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["completed_stages"], [])
        self.assertFalse((self.out / "demo-report.json").exists())
        self.assertFalse((self.out / "DEMO_IN_PROGRESS.json").exists())

    def test_complete_demo_through_real_existing_clis(self):
        pair = executable_pair()
        if pair is None:
            self.skipTest("existing ffmpeg with libass/QC filters and ffprobe required; set DEMO_TEST_FFMPEG / DEMO_TEST_FFPROBE")
        ffmpeg, ffprobe = pair
        result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(self.out), "--ffmpeg", ffmpeg, "--ffprobe", ffprobe], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "success")
        self.assertEqual(len(report["completed_stages"]), 9)
        for field in ("technical_full_decode", "archive_hashes_verified", "source_unchanged", "fictional"):
            self.assertTrue(report[field])
        for field in ("scientific_acceptance", "player_acceptance", "human_acceptance"):
            self.assertFalse(report[field])
        self.assertEqual(report["wall_review_status"], "pending")
        self.assertIn("not narration", report["audio"])
        self.assertTrue((self.out / "delivery/film.mp4").stat().st_size > 1000)
        self.assertTrue((self.out / "manuscript/narration.docx").is_file())
        self.assertIn("Style: Title", (self.out / "delivery/layers.ass").read_text())
        reviews = json.loads((self.out / "wall/reviews.json").read_text())
        self.assertTrue(all(a["review_status"] == "pending" for a in reviews["assets"].values()))
        manifest = json.loads((self.out / "archive/archive-manifest.json").read_text())
        paths = {Path(row["original_path"]).relative_to(self.out.resolve()).as_posix() for row in manifest["files"]}
        self.assertTrue({"media/synthetic.mp4", "delivery/film.mp4", "edit.json", "archive-plan.json", "rebuild-tools/scripts/demo_project.py"}.issubset(paths))
        verification = subprocess.run([sys.executable, str(SCRIPT.parent / "archive_tools.py"), "verify", str(self.out / "archive")], capture_output=True, text=True, timeout=20)
        self.assertEqual(verification.returncode, 0, verification.stderr)
        self.assertTrue(json.loads(verification.stdout)["hashes_verified"])
        self.assertFalse((self.out / "demo-failed.json").exists())
        self.assertFalse((self.out / "DEMO_IN_PROGRESS.json").exists())


if __name__ == "__main__":
    unittest.main()
