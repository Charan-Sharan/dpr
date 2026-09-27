import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import providers


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GROQ_API_KEY": "groq-test-secret", "OPEN_ROUTER_API_KEY": "router-test-secret"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_env_loading_preserves_process_config_and_ignores_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('GROQ_API_KEY=local-value\nexport OPENROUTER_API_KEY="quoted-key" # note\nDPR_PROVIDER=openrouter\n')
            providers.load_env(path)
        self.assertEqual(providers.api_key("groq"), "groq-test-secret")
        self.assertEqual(os.environ["OPENROUTER_API_KEY"], "quoted-key")
        self.assertEqual(providers.provider_order("planner"), ["openrouter", "groq"])

    def test_placeholder_rejection_and_openrouter_alias(self):
        os.environ["GROQ_API_KEY"] = "your_actual_key_here"
        os.environ["OPEN_ROUTER_API_KEY"] = "your_actual_key_here"
        self.assertEqual(providers.provider_order("planner"), [])
        with self.assertRaisesRegex(ValueError, "Placeholder"):
            providers.llm("planner", "test", {})
        os.environ["OPENROUTER_API_KEY"] = "alias-key"
        self.assertEqual(providers.provider_order("writer"), ["openrouter"])

    def test_per_provider_models_and_automatic_role_routing(self):
        self.assertEqual(providers.provider_order("skeptic"), ["openrouter", "groq"])
        self.assertEqual(providers.provider_order("writer"), ["groq", "openrouter"])
        os.environ["DPR_MODEL_PLANNER"] = "legacy-groq"
        self.assertEqual(providers.model_for("groq", "planner"), "legacy-groq")
        self.assertNotEqual(providers.model_for("openrouter", "planner"), "legacy-groq")

    def test_forbidden_falls_back_and_does_not_leak_key(self):
        failure = HTTPError("https://api.groq.com", 403, "Forbidden", {},
                            io.BytesIO(json.dumps({"error": {"message": "Access denied groq-test-secret"}}).encode()))
        success = io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}]}).encode())
        messages = []
        with patch.object(providers.request, "urlopen", side_effect=[failure, success]) as call:
            self.assertEqual(providers.llm("planner", "JSON", {}, messages.append), {"ok": True})
        self.assertEqual(call.call_count, 2)
        self.assertIn("openrouter.ai", call.call_args.args[0].full_url)
        self.assertNotIn("groq-test-secret", " ".join(messages))
        self.assertIn("HTTP 403", " ".join(messages))

    def test_rate_limit_retries_are_bounded(self):
        os.environ.pop("OPEN_ROUTER_API_KEY")
        with patch.object(providers, "complete", side_effect=providers.ProviderError("rate limited", True)), \
                patch.object(providers.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "All configured providers failed"):
                providers.llm("writer", "JSON", {})
        sleep.assert_called_once()

    def test_invalid_json_and_http_200_error_are_rejected(self):
        responses = [b'{"choices":[{"message":{"content":"not json"}}]}',
                     b'{"error":{"code":402,"message":"Insufficient credits"}}']
        for body in responses:
            with patch.object(providers.request, "urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises(providers.ProviderError):
                    providers.complete("openrouter", "planner", "JSON", {})

    def test_truncated_generation_is_not_committed(self):
        body = b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}'
        with patch.object(providers.request, "urlopen", return_value=io.BytesIO(body)):
            with self.assertRaisesRegex(providers.ProviderError, "token limit"):
                providers.complete("groq", "writer", "JSON", {})
