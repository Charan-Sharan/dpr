"""Browser and HTTP integration with mocked providers and a disposable database."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import core
import providers
import server


class ScholarshipBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("chromium"), "Chromium is not installed")
    def test_scholarship_workflow(self):
        class Handler(server.Handler):
            def do_GET(self):
                if self.path == "/__test":
                    return self.send(Path(__file__).with_name("scholarship_browser.html").read_bytes(), content_type="text/html")
                return super().do_GET()

            def log_message(self, *args):
                pass

        counter = 0
        def model(provider, role, system, payload, **kwargs):
            nonlocal counter
            counter += 1
            if "Break the user's instruction" in system:
                return {"tasks": [{"operation": "revise_section", "section_id": core.paper()["sections"][0]["id"], "instruction": "Revise introduction", "depends_on": []}]}
            if "block_id:null|string,text,claims" in system:
                return {"section_id": payload["section"]["id"], "operation": "replace_section", "text": "Proposed scope.", "claims": [{"text": "A general claim", "citations": []}]}
            if "unsupported_claims:[string]" in system:
                return {"unsupported_claims": [], "objections": [], "rationale": "No empirical assertions"}
            if "Independently review" in system:
                return {"objections": [], "rationale": "Clear scope"}
            if "hand_raise:boolean" in system:
                return {"hand_raise": True, "priority": 2, "confidence": .7, "pointer": "Investigate alternatives " + payload["perspective"], "relevant": True}
            if "summary:string" in system:
                return {"summary": "Researcher chooses next steps", "disagreements": ["Alternative explanation"], "missing_evidence": ["Measurements"], "choices": ["Supply evidence"]}
            return {"text": "Perspective contribution " + str(counter), "assumptions": ["Unverified assumption"], "alternatives": ["Competing account"], "open_questions": ["What evidence?"]}

        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DB", Path(directory) / "test.sqlite3"), \
                patch.object(providers, "complete", side_effect=model), \
                patch.dict(os.environ, {"GROQ_API_KEY": "test-only", "OPEN_ROUTER_API_KEY": "test-only"}):
            core.save_markdown("# Paper\n\n## Introduction\n\nOriginal prose.\n", core.paper()["id"])
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([shutil.which("chromium"), "--headless", "--no-sandbox", "--disable-gpu",
                    "--disable-dev-shm-usage", "--no-proxy-server", "--no-first-run", "--user-data-dir=" + directory + "/browser",
                    "--dump-dom", "--virtual-time-budget=90000", f"http://127.0.0.1:{httpd.server_port}/__test"],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                marker = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
                test_result = marker.group(1) if marker else result.stdout[:2000]
                self.assertTrue(test_result.startswith("PASS:"), test_result + result.stderr[-1000:])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join()
