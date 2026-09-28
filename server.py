"""Local single-researcher web API for the DPR workspace."""
import json
import mimetypes
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import core
import scholarship

ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
    def send(self, value, status=200, content_type="application/json"):
        data = json.dumps(value).encode() if content_type == "application/json" else value
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # React cancels polling when switching projects or leaving the page.
            # The disconnected client cannot receive another error response.
            return

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8_000_000:
            raise ValueError("Upload exceeds 8 MB")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        try:
            project_id = parse_qs(urlparse(self.path).query).get("project", ["default"])[0]
            with core.project_scope(project_id):
                self.get_response()
        except ValueError as exc:
            return self.send({"error": str(exc)}, 400)

    def get_response(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/projects":
                return self.send(core.all_items("project"))
            if path == "/api/state":
                return self.send({"project": core.get("project", core.PROJECT.get()), "projects": core.all_items("project"),
                                  "scholarship": scholarship.snapshot(),
                                  "providers": core.providers.status(),
                                  "paper": core.paper(), "sources": [{"id": e["id"], "title": e["title"]} for e in core.all_items("evidence")],
                                  "jobs": [core.present_job(job) for job in core.all_items("job")], "events": core.all_items("event"),
                                  "versions": [{"id": v["id"], "number": v["number"], "prompt": v["prompt"], "at": v["at"]} for v in core.all_items("version")]})
            if path == "/api/sessions":
                return self.send(scholarship.snapshot())
            if path == "/api/audit":
                return self.send(scholarship.audit_export())
            if path.startswith("/api/sessions/"):
                parts = path.split("/")
                session = scholarship.present_session(scholarship.get(parts[3]))
                if len(parts) == 5 and parts[4] == "events":
                    after = int(parse_qs(urlparse(self.path).query).get("after", ["0"])[0])
                    return self.send([e for e in session["activity"] if e["seq"] > after])
                return self.send(session)
            if path == "/api/latex":
                return self.send(core.latex(core.paper()).encode(), content_type="text/plain")
            if path == "/api/markdown":
                return self.send(core.markdown(core.paper()).encode(), content_type="text/markdown")
            if path.startswith("/api/source/"):
                source = core.get("evidence", path.split("/")[-1])
                return self.send(source or {"error": "Not found"}, 200 if source else 404)
            if path.startswith("/api/version/"):
                version = core.get("version", path.split("/")[-1])
                return self.send(version or {"error": "Not found"}, 200 if version else 404)
            path = "/index.html" if path == "/" else path
            file = (ROOT / "static" / path.lstrip("/")).resolve()
            if not file.is_relative_to((ROOT / "static").resolve()) or not file.is_file():
                return self.send({"error": "Not found"}, 404)
            return self.send(file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or "application/octet-stream")
        except Exception as exc:
            return self.send({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            project_id = parse_qs(urlparse(self.path).query).get("project", ["default"])[0]
            with core.project_scope(project_id):
                self.post_response()
        except ValueError as exc:
            return self.send({"error": str(exc)}, 400)

    def post_response(self):
        try:
            data = self.body()
            path = urlparse(self.path).path
            if path == "/api/projects":
                return self.send(core.create_project(data.get("name")), 201)
            if path == "/api/scholarship":
                return self.send(scholarship.settings(data.get("enabled")))
            if path == "/api/memory":
                return self.send(scholarship.update_memory(data.get("id"), data.get("action"), data.get("text", "")))
            if path.startswith("/api/sessions/"):
                parts = path.split("/")
                session_id = parts[3]
                if len(parts) != 5:
                    raise ValueError("Specify a session action")
                action = parts[4]
                if action == "decide":
                    job = scholarship.decide(session_id, data.get("task_id"), data.get("choice"), data.get("rationale", ""))
                else:
                    job = scholarship.control(session_id, action, data.get("text", ""), data.get("panel"), data.get("reply_to"))
                if job["status"] == "queued":
                    scholarship.launch(job["id"])
                return self.send(job)
            if path == "/api/sessions" or (path == "/api/run" and scholarship.enabled()):
                if not scholarship.enabled():
                    raise ValueError("Enable DPR scholarship for this project first")
                job = scholarship.create(data.get("prompt"), data.get("mode", "auto"), data.get("selection"), data.get("source_ids"), data.get("allow_all", False))
                scholarship.launch(job["id"])
                return self.send(job, 202)
            if path == "/api/run":
                prompt = str(data.get("prompt", "")).strip()
                if not prompt or len(prompt) > 12000:
                    raise ValueError("Enter a prompt of at most 12,000 characters")
                if not any(p["configured"] for p in core.providers.status()):
                    raise ValueError("Set a real GROQ_API_KEY or OPEN_ROUTER_API_KEY in .env, then restart the server. Placeholder values are not API keys.")
                with core.LOCK:
                    if any(j["status"] in ("queued", "running") for j in core.all_items("job")):
                        raise ValueError("A request is already running. Wait for it to finish.")
                    selection = data.get("selection")
                    if selection is not None:
                        core.validate_selection(selection, core.paper())
                    source_ids = core.validate_source_ids(data.get("source_ids", []), core.source_context())
                    job = {"id": core.uid(), "prompt": prompt, "selection": selection,
                           "source_ids": source_ids, "allow_all": data.get("allow_all") is True,
                           "project_id": core.PROJECT.get(), "status": "queued", "tasks": [], "at": core.time.time()}
                    core.put("job", job)
                threading.Thread(target=core.run_job, args=(job["id"], job["project_id"]), daemon=True).start()
                return self.send(job, 202)
            if path == "/api/evidence":
                title = str(data.get("title", "")).strip()[:200]
                body = str(data.get("text", ""))
                if not title or not body.strip() or len(body) > 500000:
                    raise ValueError("Provide a title and up to 500,000 characters of evidence")
                item = {"id": core.uid(), "title": title, "text": body, "at": core.time.time()}
                core.put("evidence", item)
                return self.send(item, 201)
            if path == "/api/evidence/pdf":
                import base64
                title = str(data.get("title", "")).strip()[:200]
                raw = base64.b64decode(data.get("base64", ""), validate=True)
                if not title or len(raw) > 8_000_000 or not raw.startswith(b"%PDF"):
                    raise ValueError("Provide a PDF up to 8 MB")
                with tempfile.TemporaryDirectory() as directory:
                    pdf = Path(directory) / "source.pdf"
                    pdf.write_bytes(raw)
                    proc = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=20)
                    if proc.returncode or not proc.stdout.strip():
                        raise ValueError("PDF text extraction failed; paste its text instead")
                    item = {"id": core.uid(), "title": title, "text": proc.stdout[:500000], "at": core.time.time()}
                core.put("evidence", item)
                return self.send(item, 201)
            if path == "/api/decide":
                existing = core.get("job", data["job_id"])
                if existing and existing.get("schema") == scholarship.SCHEMA:
                    job = scholarship.decide(data["job_id"], data["task_id"], data["choice"], data.get("rationale", ""))
                    if job["status"] == "queued":
                        scholarship.launch(job["id"])
                    return self.send(job)
                if scholarship.enabled():
                    raise ValueError("Legacy proposal: request a fresh revision under the new workflow")
                job = core.decide(data["job_id"], data["task_id"], data["choice"])
                if job["status"] == "queued":
                    threading.Thread(target=core.run_job, args=(job["id"], job["project_id"]), daemon=True).start()
                return self.send(job)
            if path == "/api/undo":
                return self.send(core.undo())
            if path == "/api/markdown":
                return self.send(core.save_markdown(data.get("markdown"), data.get("base_version")))
            if path == "/api/title":
                name = str(data.get("title", "")).strip()[:200]
                if not name:
                    raise ValueError("Title required")
                with core.LOCK, core.connect() as db:
                    version = core.paper()
                    new = dict(version, id=core.uid(), number=version["number"] + 1,
                               parent=version["id"], at=core.time.time(), prompt="Changed title", title=name)
                    core.put("version", new, db)
                    core.put("meta", {"id": "current", "version": new["id"]}, db)
                    db.commit()
                return self.send(new)
            return self.send({"error": "Not found"}, 404)
        except Exception as exc:
            return self.send({"error": str(exc)}, 400)


if __name__ == "__main__":
    scholarship.migrate()
    scholarship.recover()
    core.paper()
    port = int(os.environ.get("PORT", "8765"))
    print(f"DPR workspace: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
