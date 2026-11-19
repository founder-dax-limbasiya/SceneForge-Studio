import tempfile
import unittest
from pathlib import Path

from submit_scene_jobs import (
    apply_job,
    enabled_worker_ids,
    format_worker_list,
    extract_prompt,
    read_checkpoint,
    safe_master_url,
    validate_workflow,
    save_checkpoint,
)


class SubmitterTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {
            "prompt": {
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}},
                "7": {"class_type": "KSampler", "inputs": {"seed": 1}},
                "8": {"class_type": "WanImageToVideo", "inputs": {"length": 81, "width": 832, "height": 480}},
                "9": {"class_type": "DistributedCollector", "inputs": {"load_balance": True}},
                "10": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
            }
        }
        self.job = {
            "jobId": "scene-1",
            "prompt": "A cinematic wide shot",
            "negativePrompt": "blur, artifacts",
            "seed": 123,
            "durationSeconds": 5,
            "frameRate": 16,
            "frameCount": 81,
            "requestedOutput": {"width": 832, "height": 480},
        }

    def test_extract_api_prompt(self):
        self.assertIn("6", extract_prompt(self.workflow))

    def test_replace_prompt_and_seed_without_mutating_template(self):
        result = apply_job(self.workflow["prompt"], self.job, "6", "text", "7", "seed")
        self.assertEqual(result["6"]["inputs"]["text"], "A cinematic wide shot")
        self.assertEqual(result["7"]["inputs"]["seed"], 123)
        self.assertEqual(self.workflow["prompt"]["6"]["inputs"]["text"], "old prompt")

    def test_maps_frames_and_dimensions(self):
        result = apply_job(
            self.workflow["prompt"], self.job, "6", "text",
            frames_node_id="8", width_node_id="8", height_node_id="8",
        )
        self.assertEqual(result["8"]["inputs"]["length"], 81)
        self.assertEqual(result["8"]["inputs"]["width"], 832)
        self.assertEqual(result["8"]["inputs"]["height"], 480)

    def test_maps_negative_prompt(self):
        result = apply_job(
            self.workflow["prompt"], self.job, "6", "text",
            negative_node_id="10", negative_input="text",
        )
        self.assertEqual(result["10"]["inputs"]["text"], "blur, artifacts")
        self.assertEqual(self.workflow["prompt"]["10"]["inputs"]["text"], "old negative")

    def test_calculates_frames_when_missing(self):
        job = dict(self.job)
        job.pop("frameCount")
        result = apply_job(self.workflow["prompt"], job, "6", "text", frames_node_id="8")
        self.assertEqual(result["8"]["inputs"]["length"], 81)

    def test_missing_prompt_node_fails(self):
        with self.assertRaises(ValueError):
            apply_job(self.workflow["prompt"], {"prompt": "x"}, "99", "text")

    def test_missing_dimension_fails(self):
        job = dict(self.job)
        job["requestedOutput"] = {}
        with self.assertRaises(ValueError):
            apply_job(self.workflow["prompt"], job, "6", "text", width_node_id="8")

    def test_http_internet_url_rejected(self):
        with self.assertRaises(ValueError):
            safe_master_url("http://example.com:8188")

    def test_localhost_http_allowed(self):
        self.assertEqual(safe_master_url("http://127.0.0.1:8188/"), "http://127.0.0.1:8188")

    def test_url_credentials_rejected(self):
        with self.assertRaises(ValueError):
            safe_master_url("https://user:secret@example.com")

    def test_auto_worker_discovery_uses_enabled_ids_only(self):
        config = {"workers": [
            {"id": "1", "name": "GPU A", "enabled": True, "type": "local"},
            {"id": "2", "name": "GPU B", "enabled": False, "type": "remote"},
            {"id": "cloud-3", "name": "Cloud GPU", "enabled": True, "type": "cloud"},
        ]}
        self.assertEqual(enabled_worker_ids(config), ["1", "cloud-3"])

    def test_worker_list_omits_host_details(self):
        config = {"workers": [
            {"id": "1", "name": "GPU A", "enabled": True, "type": "local", "host": "10.0.0.1"}
        ]}
        lines = format_worker_list(config)
        self.assertEqual(lines, ["1\tGPU A\tlocal\tenabled"])
        self.assertNotIn("10.0.0.1", "\n".join(lines))

    def test_collector_and_load_balance_required(self):
        validate_workflow(self.workflow["prompt"])
        with self.assertRaises(ValueError):
            validate_workflow({"3": {"class_type": "DistributedCollector", "inputs": {"load_balance": False}}})

    def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            original = {"scene-1": {"prompt_id": "abc-123", "worker_count": 2}}
            save_checkpoint(path, original)
            self.assertEqual(read_checkpoint(path), original)

    def test_legacy_checkpoint_compatibility(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            path.write_text('{"queued_job_ids":["scene-1"]}', encoding="utf-8")
            self.assertEqual(read_checkpoint(path)["scene-1"]["legacy"], True)


if __name__ == "__main__":
    unittest.main()
