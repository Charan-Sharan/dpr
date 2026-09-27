import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import core


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = patch.object(core, "DB", Path(temporary.name) / "projects.db")
        database.start()
        self.addCleanup(database.stop)

    def test_legacy_document_preserved_and_projects_isolate_all_records(self):
        legacy = core.save_markdown("# Existing paper\n\n## Intro\n\nKeep this", core.paper()["id"])
        core.put("evidence", {"id": "source", "title": "Old source", "text": "Legacy evidence"})
        core.put("job", {"id": "old-job", "status": "error"})
        core.ensure_projects()
        project = core.create_project("Second paper")
        with core.project_scope(project["id"]):
            self.assertEqual(core.paper()["title"], "Second paper")
            self.assertEqual(core.source_context(), [])
            self.assertEqual(core.all_items("job"), [])
            self.assertIsNone(core.get("version", legacy["id"]))
            self.assertIsNone(core.get("evidence", "source"))
            self.assertEqual(len(core.all_items("version")), 1)
            core.save_markdown("# Second draft", core.paper()["id"])
            core.undo()
            self.assertEqual(core.paper()["title"], "Second paper")
        self.assertEqual(core.paper(), legacy)
        self.assertEqual(core.get("evidence", "source")["text"], "Legacy evidence")
        self.assertEqual(len(core.all_items("project")), 2)

    def test_background_job_stays_in_originating_project(self):
        first = core.create_project("First")
        second = core.create_project("Second")
        with core.project_scope(first["id"]):
            core.put("job", {"id": "worker", "prompt": "Add implementation", "tasks": [], "status": "queued"})
        def model(role, system, payload):
            if role == "planner":
                self.assertEqual(payload["document"]["title"], "First")
                return {"tasks": [{"section_id": None, "heading": "Implementation", "instruction": "Write steps", "change_requested": True}]}
            if role == "writer":
                return {"section_id": payload["section"]["id"], "operation": "append", "text": "- Gather notes", "claims": []}
            return {"objections": [], "unsupported_claims": []}
        with core.project_scope(second["id"]), patch.object(core, "llm", side_effect=model):
            worker = threading.Thread(target=core.run_job, args=("worker", first["id"]))
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(core.paper()["sections"], [])
            self.assertEqual(core.all_items("job"), [])
            self.assertEqual(core.all_items("event"), [])
        with core.project_scope(first["id"]):
            self.assertEqual(core.get("job", "worker")["status"], "complete")
            self.assertEqual(core.paper()["sections"][0]["heading"], "Implementation")
            self.assertTrue(core.all_items("event"))

    def test_unknown_project_rejected_and_scope_restored(self):
        with self.assertRaisesRegex(ValueError, "Unknown project"):
            with core.project_scope("missing"):
                self.fail("Must not enter unknown scope")
        project = core.create_project("Valid")
        with self.assertRaises(RuntimeError):
            with core.project_scope(project["id"]):
                raise RuntimeError("exit")
        self.assertEqual(core.PROJECT.get(), "default")

    def test_record_updates_do_not_reorder_creation_history(self):
        core.put("job", {"id": "first", "at": 10, "status": "complete"})
        core.put("job", {"id": "second", "at": 20, "status": "complete"})
        # Simulate rows moved by the old INSERT OR REPLACE implementation.
        with core.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)",
                       ("job", "first", '{"id":"first","at":10,"status":"rejected"}'))
        self.assertEqual([j["id"] for j in core.all_items("job")], ["first", "second"])
        core.put("event", {"id": "one", "at": 30})
        core.put("event", {"id": "two", "at": 30})
        core.put("event", {"id": "one", "at": 30, "message": "Updated"})
        self.assertEqual([e["id"] for e in core.all_items("event")], ["one", "two"])

    def test_selected_sources_are_project_scoped_and_prioritized(self):
        core.put("evidence", {"id": "first", "title": "Repeated name", "text": "Old source " * 8000})
        core.put("evidence", {"id": "chosen", "title": "Repeated name", "text": "Relevant survey passage."})
        sources = core.source_context()
        self.assertEqual(core.validate_source_ids(["chosen"], sources), ["chosen"])
        ordered = core.prioritize_sources(sources, ["chosen"])
        self.assertEqual([source["id"] for source in ordered], ["chosen", "first"])
        self.assertEqual(core.model_sources(ordered, "survey", ["chosen"])[0]["text"], "Relevant survey passage.")
        project = core.create_project("Another project")
        with core.project_scope(project["id"]):
            with self.assertRaisesRegex(ValueError, "not available"):
                core.validate_source_ids(["chosen"], core.source_context())
