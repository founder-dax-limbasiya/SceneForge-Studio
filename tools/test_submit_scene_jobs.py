import unittest

from submit_scene_jobs import apply_job, extract_prompt, safe_master_url, validate_workflow


class SubmitterTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {
            "prompt": {
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}},
                "7": {"class_type": "KSampler", "inputs": {"seed": 1}},
                "9": {"class_type": "DistributedCollector", "inputs": {"load_balance": True}},
            }
        }

    def test_extract_api_prompt(self):
        self.assertIn("6", extract_prompt(self.workflow))

    def test_replace_prompt_and_seed(self):
        job = {"jobId": "scene-1", "prompt": "A cinematic wide shot", "seed": 123}
        result = apply_job(self.workflow["prompt"], job, "6", "text", "7", "seed")
        self.assertEqual(result["6"]["inputs"]["text"], "A cinematic wide shot")
        self.assertEqual(result["7"]["inputs"]["seed"], 123)
        self.assertEqual(self.workflow["prompt"]["6"]["inputs"]["text"], "old prompt")

    def test_missing_prompt_node_fails(self):
        with self.assertRaises(ValueError):
            apply_job(self.workflow["prompt"], {"prompt": "x"}, "99", "text")

    def test_http_internet_url_rejected(self):
        with self.assertRaises(ValueError):
            safe_master_url("http://example.com:8188")

    def test_localhost_http_allowed(self):
        self.assertEqual(safe_master_url("http://127.0.0.1:8188/"), "http://127.0.0.1:8188")

    def test_collector_and_load_balance_required(self):
        validate_workflow(self.workflow["prompt"])
        with self.assertRaises(ValueError):
            validate_workflow({"3": {"class_type": "DistributedCollector", "inputs": {"load_balance": False}}})


if __name__ == "__main__":
    unittest.main()
