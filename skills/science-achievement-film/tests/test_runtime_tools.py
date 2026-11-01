"""Offline tests only: never contact generation services or launch GUI apps."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rt = load("runtime_tools", ROOT / "scripts/runtime_tools.py")
seedance = load("seedance_http", ROOT / "references/integrations/seedance_http.py")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = {"tasks": {}}

    def task(self, kind="local-analysis", attempts=2):
        return rt.register(self.data, self.root, "shot01", kind, outputs=[self.root / "new.mp4"], max_attempts=attempts)

    def test_filters_distinguish_partial_ffmpeg_build(self):
        result = rt.parse_filters(" TSC subtitles V->V description\n .. loudnorm A->A description\n")
        self.assertTrue(result["subtitles"])
        self.assertTrue(result["loudnorm"])
        self.assertFalse(result["freezedetect"])

    def test_config_environment_and_unknown_fields(self):
        with patch.dict(os.environ, {"SCIENCE_FILM_FFMPEG": "custom-ffmpeg"}):
            self.assertEqual(rt.load_config()["tools"]["ffmpeg"][0], "custom-ffmpeg")
        file = self.root / "bad.json"
        file.write_text('{"tools":{"arbitrary_shell":["sh"]}}')
        with self.assertRaises(ValueError): rt.load_config(file)

    def test_doctor_does_not_read_or_echo_secret(self):
        secret = self.root / "private-config"
        secret.write_text("SENSITIVE_TEST_SENTINEL")
        config = rt.load_config()
        config["secret_files"]["seedance_api_key"] = str(secret)
        with patch.object(rt, "resolve_tool", return_value=None):
            report = rt.doctor(config)
        self.assertTrue(report["secret_files"]["seedance_api_key"]["present_nonempty"])
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", json.dumps(report))
        self.assertNotIn(str(secret), json.dumps(report))

    def test_remote_health_and_credentials_rejected(self):
        for url in ("https://example.com/health", "http://user:pass@127.0.0.1/health", "http://127.0.0.1/health?key=x"):
            with self.assertRaises(ValueError): rt.local_health(url)

    def test_request_only_stored_as_fingerprint(self):
        request = self.root / "request.json"
        request.write_text('{"input":"PRIVATE_SENTINEL"}')
        task = rt.register(self.data, self.root, "shot01", "seedance", request)
        self.assertEqual(len(task["request_sha256"]), 64)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(task))
        with self.assertRaises(ValueError): rt.register(self.data, self.root, "shot01", "seedance")

    def test_output_escape_existing_and_symlink_rejected(self):
        for path in (self.root.parent / "escape.mp4", self.root / "../escape.mp4"):
            with self.assertRaises(ValueError): rt.register(self.data, self.root, "escape", "local-analysis", outputs=[path])
        existing = self.root / "existing.mp4"
        existing.write_bytes(b"original")
        with self.assertRaises(ValueError): rt.register(self.data, self.root, "existing", "local-analysis", outputs=[existing])
        if hasattr(os, "symlink"):
            link = self.root / "link"
            link.symlink_to(self.root.parent, target_is_directory=True)
            with self.assertRaises(ValueError): rt.register(self.data, self.root, "link", "local-analysis", outputs=[link / "escape.mp4"])

    def test_remote_unknown_never_retries(self):
        task = self.task("seedance")
        rt.transition(task, self.root, "running")
        rt.transition(task, self.root, "unknown")
        self.assertEqual(rt.retry_plan(task)["action"], "reconcile_service_history")
        with self.assertRaises(ValueError): rt.reset_for_retry(task)

    def test_remote_id_is_immutable(self):
        task = self.task("seedance")
        with self.assertRaises(ValueError): rt.transition(task, self.root, "submitted")
        rt.transition(task, self.root, "submitted", "task_123")
        with self.assertRaises(ValueError): rt.transition(task, self.root, "running", "task_456")
        self.assertEqual(task["external_id"], "task_123")
        self.assertEqual(rt.retry_plan(task)["action"], "query_existing")

    def test_local_retries_bounded_and_partial_output_preserved(self):
        task = self.task()
        rt.transition(task, self.root, "running")
        rt.transition(task, self.root, "failed")
        (self.root / "new.mp4").write_bytes(b"partial")
        with self.assertRaises(ValueError): rt.reset_for_retry(task)
        (self.root / "new.mp4").rename(self.root / "failed-candidate.mp4")
        rt.reset_for_retry(task)
        rt.transition(task, self.root, "running")
        rt.transition(task, self.root, "failed")
        self.assertFalse(rt.retry_plan(task)["may_retry"])
        self.assertEqual((self.root / "failed-candidate.mp4").read_bytes(), b"partial")

    def test_success_needs_outputs_and_evidence(self):
        task = self.task()
        rt.transition(task, self.root, "running")
        with self.assertRaises(ValueError): rt.transition(task, self.root, "succeeded")
        (self.root / "new.mp4").write_bytes(b"fixture")
        evidence = self.root / "probe.json"
        evidence.write_text('{"fixture_only":true}')
        rt.transition(task, self.root, "succeeded", evidence=[evidence])
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(len(task["evidence"][0]["sha256"]), 64)

    def test_transaction_releases_lock_on_failure(self):
        ledger = self.root / "jobs.json"
        with self.assertRaises(ValueError):
            with rt.ledger_transaction(ledger, self.root):
                raise ValueError("abort")
        self.assertFalse(ledger.exists())
        self.assertFalse((self.root / "jobs.json.lock").exists())
        with rt.ledger_transaction(ledger, self.root) as (data, root):
            rt.register(data, root, "new", "local-analysis")
        self.assertIn("new", json.loads(ledger.read_text())["tasks"])

    def test_success_rechecks_output_symlink_scope(self):
        task = self.task()
        rt.transition(task, self.root, "running")
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.mp4"
            target.write_bytes(b"outside")
            (self.root / "new.mp4").symlink_to(target)
            evidence = self.root / "probe.json"
            evidence.write_text('{}')
            with self.assertRaises(ValueError): rt.transition(task, self.root, "succeeded", evidence=[evidence])


class SeedanceClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.request = self.root / "request.json"
        self.request.write_text(json.dumps({"model": "test-model", "content": [{"type": "text", "text": "Test clip"}]}))
        self.key = self.root / "api-key"
        self.key.write_text("SENSITIVE_TEST_SENTINEL")
        self.journal = self.root / "job.json"

    def call(self, action, *extras):
        args = [action, "--request", str(self.request), "--journal", str(self.journal), "--key-file", str(self.key), "--base-url", seedance.API_BASE, *extras]
        output = io.StringIO()
        with contextlib.redirect_stdout(output): result = seedance.main(args)
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", output.getvalue())
        return result, output.getvalue()

    def test_validate_is_offline_and_submit_requires_explicit_switch(self):
        with patch.object(seedance, "send") as send:
            self.assertEqual(self.call("validate")[0], 0)
            self.assertEqual(self.call("submit")[0], 2)
            send.assert_not_called()

    def test_ambiguous_post_keeps_unknown_and_prevents_resubmit(self):
        with patch.object(seedance, "send", side_effect=TimeoutError("test")) as send:
            self.assertEqual(self.call("submit", "--allow-billable")[0], 2)
            self.assertEqual(json.loads(self.journal.read_text())["status"], "unknown")
            self.assertEqual(self.call("submit", "--allow-billable")[0], 2)
            self.assertEqual(send.call_count, 1)

    def test_submit_then_query_does_not_leak_signed_url(self):
        with patch.object(seedance, "send", return_value={"id": "task_123"}):
            self.assertEqual(self.call("submit", "--allow-billable")[0], 0)
        with patch.object(seedance, "send", return_value={"status": "succeeded", "content": {"video_url": "https://example.invalid/v?private=SIGNED_SENTINEL"}}):
            result, output = self.call("query")
        self.assertEqual(result, 0)
        self.assertNotIn("SIGNED_SENTINEL", output + self.journal.read_text())

    def test_api_base_disallows_credentials_and_insecure_transport(self):
        for url in ("http://example.invalid", "https://user:pass@example.invalid", "https://example.invalid/?key=x",
                    "https://ark.cn-beijing.volces.com.evil.invalid/api/v3", "https://ark.cn-beijing.volces.com:444/api/v3",
                    "https://ark.cn-beijing.volces.com/api/other", "https://example.invalid/api/v3"):
            with self.assertRaises(ValueError): seedance.endpoint(url)

    def test_existing_foreign_lock_is_not_removed(self):
        lock = self.root / "job.json.lock"
        lock.write_text("another process")
        self.assertEqual(self.call("submit", "--allow-billable")[0], 2)
        self.assertTrue(lock.exists())

    def test_query_endpoint_must_match_submission(self):
        with patch.object(seedance, "send", return_value={"id": "task_123"}):
            self.assertEqual(self.call("submit", "--allow-billable")[0], 0)
        with patch.object(seedance, "send") as send:
            result, _ = self.call("query", "--base-url", "https://different.invalid/api/v3")
            self.assertEqual(result, 2)
            send.assert_not_called()

    def test_unknown_credential_fields_in_payload_rejected(self):
        self.request.write_text('{"model":"test-model","content":[{"type":"text","text":"test"}],"api_key":"DO_NOT_TRANSMIT"}')
        with patch.object(seedance, "send") as send:
            result, output = self.call("submit", "--allow-billable")
            self.assertEqual(result, 2)
            self.assertNotIn("DO_NOT_TRANSMIT", output)
            send.assert_not_called()

    def test_authenticated_send_rejects_untrusted_url_before_network(self):
        for url in ("https://evil.invalid/api/v3/contents/generations/tasks",
                    seedance.API_BASE + "/contents/generations/tasks?forward=evil",
                    seedance.API_BASE + "/contents/generations/tasks/../../other",
                    "https://user:password" + "@" + "ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"):
            with patch.object(seedance, "build_opener") as opener:
                with self.assertRaises(ValueError): seedance.send(url, "SENSITIVE_TEST_SENTINEL")
                opener.assert_not_called()

    def test_download_rejects_untrusted_hosts_before_network_or_file(self):
        trusted = next(iter(seedance.DOWNLOAD_HOSTS))
        for url in ("https://127.0.0.1/private", "https://evil.invalid/movie.mp4",
                    f"https://{trusted}.evil.invalid/movie.mp4", f"https://{trusted}:444/movie.mp4",
                    f"https://user:password@{trusted}/movie.mp4", f"https://{trusted}/movie.mp4#fragment"):
            with patch.object(seedance, "build_opener") as opener:
                with self.assertRaises(ValueError): seedance.download(url, self.root / "movie.mp4")
                opener.assert_not_called()
                self.assertFalse((self.root / "movie.mp4.part").exists())

    def test_download_has_no_authorization_header(self):
        url = "https://" + next(iter(seedance.DOWNLOAD_HOSTS)) + "/movie.mp4?signature=PRIVATE_SIGNED_URL"
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = [b"movie-fixture", b""]
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(seedance, "build_opener", return_value=opener):
            seedance.download(url, self.root / "movie.mp4")
        self.assertIsInstance(opener.open.call_args.args[0], str)
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 60})
        self.assertEqual((self.root / "movie.mp4").read_bytes(), b"movie-fixture")

    def test_redirect_is_never_followed(self):
        self.assertIsNone(seedance.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid"))

    def test_unexpected_exception_and_argument_error_hide_secrets(self):
        with patch.object(seedance, "send", side_effect=RuntimeError("SENSITIVE_TEST_SENTINEL")):
            self.assertEqual(self.call("submit", "--allow-billable")[0], 2)
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            seedance.main(["validate", "--unknown-secret", "SENSITIVE_TEST_SENTINEL"])
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", error.getvalue())

    def test_service_cannot_echo_key_as_task_id(self):
        with patch.object(seedance, "send", return_value={"id": "SENSITIVE_TEST_SENTINEL"}):
            result, output = self.call("submit", "--allow-billable")
        self.assertEqual(result, 2)
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", output + self.journal.read_text())

    def test_api_key_is_never_embedded_in_download_request(self):
        with patch.object(seedance, "send", return_value={"id": "task_123"}):
            self.assertEqual(self.call("submit", "--allow-billable")[0], 0)
        url = "https://" + next(iter(seedance.DOWNLOAD_HOSTS)) + "/movie.mp4?key=SENSITIVE_TEST_SENTINEL"
        with patch.object(seedance, "send", return_value={"status": "succeeded", "content": {"video_url": url}}), patch.object(seedance, "download") as download:
            result, output = self.call("query", "--download", str(self.root / "movie.mp4"))
        self.assertEqual(result, 2)
        download.assert_not_called()
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", output + self.journal.read_text())


class IntegrationDocumentTests(unittest.TestCase):
    def test_relative_markdown_links_exist_inside_package(self):
        import re
        integrations = ROOT / "references/integrations"
        for path in integrations.glob("*.md"):
            for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
                target = raw.strip("<>").split("#")[0]
                if not target or "://" in target: continue
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT), f"external local link: {path.name}")
                self.assertTrue(resolved.exists(), f"missing link: {path.name}: {target}")


if __name__ == "__main__":
    unittest.main()
