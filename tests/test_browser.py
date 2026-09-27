"""Real-browser smoke test with a temporary database and mocked model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import core
import server


class BrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("chromium"), "Chromium is not installed")
    def test_document_workflow(self):
        class Handler(server.Handler):
            def do_GET(self):
                if self.path == "/__test":
                    return self.send(Path(__file__).with_name("browser.html").read_bytes(), content_type="text/html")
                return super().do_GET()

            def log_message(self, *args):
                pass

        def model(role, system, payload):
            if role == "planner":
                if "Add an unsupported claim" in payload["prompt"]:
                    return {"tasks": [{"operation": "revise_section", "section_id": None, "heading": "Abstract",
                                       "instruction": "Add an unsupported claim", "change_requested": True}]}
                if "titled" in payload["prompt"]:
                    return {"tasks": [{"operation": "set_title", "title": "Can prompt engineering be a career option?",
                                       "section_id": None, "instruction": "Set the paper title", "change_requested": True}]}
                return {"tasks": [{"section_id": payload["selection"]["section_id"],
                                   "instruction": "Rephrase selected text", "change_requested": True}]}
            if role == "writer":
                if payload["instruction"] == "Add an unsupported claim":
                    return {"section_id": payload["section"]["id"], "operation": "append",
                            "text": "A statement accepted by the author.", "claims": [{"text": "Statement", "citations": []}]}
                block = payload["section"]["blocks"][0]
                return {"section_id": payload["section"]["id"], "block_id": block["id"],
                        "operation": "replace_block", "text": block["text"].replace("Write", "Compose", 1), "claims": []}
            return {"objections": [], "unsupported_claims": []}

        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DB", Path(directory) / "test.db"), \
                patch.object(core, "llm", side_effect=model), patch.dict(os.environ, {"GROQ_API_KEY": "test-only"}):
            draft = "# Research notes\n\n## Introduction\n\nWrite **careful** prose.\n\n- First\n- Second\n\n```md\n## code heading\n```\n\n| Hello | Test |\n| --- | --- |\n| world | yes |\n"
            draft += ("\n\nMore paper content to read." * 45)
            draft += "\n\n## Methodology\n\nMethodology text.\n\n## Results\n\nResults text.\n\n## Discussion\n\nDiscussion text.\n\n## Conclusion\n\nFinal conclusion text.\n"
            core.save_markdown(draft, core.paper()["id"])
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                completed = subprocess.run([shutil.which("chromium"), "--headless", "--no-sandbox", "--disable-gpu",
                    "--disable-dev-shm-usage", "--no-proxy-server", "--no-first-run",
                    "--user-data-dir=" + directory + "/browser", "--dump-dom", "--virtual-time-budget=15000",
                    f"http://127.0.0.1:{httpd.server_port}/__test"], capture_output=True, text=True, timeout=40)
                self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
                self.assertIn('<pre id="result">PASS:', completed.stdout, completed.stdout[:3000] + completed.stderr[-1000:])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
