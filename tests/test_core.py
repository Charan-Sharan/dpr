import os
import tempfile
import unittest
from unittest.mock import patch

import core


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db = core.DB
        core.DB = core.Path(self.tmp.name) / "test.sqlite3"
        self.version = core.paper()
        self.version = core.save_markdown("# Test paper\n\n## Abstract\n\n## Introduction\n\n## Methodology\n", self.version["id"])

    def tearDown(self):
        core.DB = self.original_db
        self.tmp.cleanup()

    def test_manual_allow_and_dependent_proposals(self):
        ids = [s['id'] for s in self.version['sections']]
        job = dict(id='manual', prompt='Edit two sections', status='queued', tasks=[], allow_all=False)
        core.put('job', job)
        def model(role, system, payload):
            if role == 'planner':
                return {'tasks': [dict(section_id=ids[i], operation='revise_section', instruction='Edit', depends_on=deps)
                                  for i, deps in ((1, []), (2, [0]))]}
            if role == 'writer':
                return dict(section_id=payload['section']['id'], operation='append', text='Proposed prose.', claims=[])
            return {'objections': []}
        with patch.object(core, 'llm', side_effect=model):
            core.run_job(job['id'])
            pending = core.get('job', job['id'])
            self.assertEqual(core.paper()['id'], self.version['id'])
            self.assertEqual([t['status'] for t in pending['tasks']], ['awaiting_approval', 'waiting'])
            allowed = core.decide(job['id'], pending['tasks'][0]['id'], 'allow')
            self.assertEqual(allowed['status'], 'queued')
            core.run_job(job['id'])
            pending = core.get('job', job['id'])
            self.assertEqual([t['status'] for t in pending['tasks']], ['committed', 'awaiting_approval'])
            core.decide(job['id'], pending['tasks'][1]['id'], 'allow')
            self.assertEqual(core.get('job', job['id'])['status'], 'complete')

    def test_allow_all_saves_reviewed_proposals_including_disagreements(self):
        section = self.version['sections'][1]
        core.put('job', dict(id='automatic', prompt='Edit', status='queued', tasks=[], allow_all=True))
        def model(role, system, payload):
            if role == 'planner':
                return {'tasks': [dict(section_id=section['id'], operation='revise_section', instruction='Edit')]}
            if role == 'writer':
                return dict(section_id=section['id'], operation='append', text='Proposed prose.', claims=[])
            return {'objections': ['Alternative interpretation']}
        with patch.object(core, 'llm', side_effect=model):
            core.run_job('automatic')
        self.assertEqual(core.get('job', 'automatic')['tasks'][0]['status'], 'committed')

    def test_missing_or_unmatched_citations_are_advisory(self):
        section = self.version["sections"][1]
        source = {"id": "src", "text": "The observed runtime was 42 seconds in this benchmark."}
        proposal = {"section_id": section["id"], "operation": "append", "text": "The algorithm is faster.",
                    "claims": [{"text": "Faster", "citations": [{"source_id": "src", "quote": "invented passage about speed"}]}]}
        self.assertIsNone(core.validate_proposal(proposal, section))
        self.assertIn("not found", core.citation_issue(proposal, [source]))
        proposal["claims"][0]["citations"] = []
        self.assertIsNone(core.validate_proposal(proposal, section))
        self.assertIn("No source citation", core.citation_issue(proposal, [source]))

    def test_partial_commit_dispute_and_undo(self):
        ids = [s["id"] for s in self.version["sections"]]
        source = {"id": "source", "title": "Experiment", "text": "The method uses calibrated sensors and recorded observations."}
        core.put("evidence", source)
        job = {"id": "job", "prompt": "Two section edits", "status": "queued", "tasks": []}
        core.put("job", job)
        tasks = [{"section_id": ids[i], "instruction": f"Edit section {i}", "depends_on": [], "change_requested": True}
                 for i in (1, 2)]
        proposal1 = {"section_id": ids[1], "operation": "append", "text": "The method uses calibrated sensors.",
                     "claims": [{"text": "Calibrated sensors", "citations": [{"source_id": "source", "quote": "The method uses calibrated sensors and recorded observations."}]}]}
        proposal2 = {"section_id": ids[2], "operation": "append", "text": "A disputed interpretation.", "claims": []}
        def fake(role, _system, payload):
            if role == "planner": return {"tasks": tasks}
            if role == "writer": return proposal1 if payload["section"]["id"] == ids[1] else proposal2
            if role in ("skeptic", "methodology"): return {"objections": ["Interpretation is contested"] if payload["section"]["id"] == ids[2] else [], "rationale": "Reviewed"}
            return {"unsupported_claims": [], "objections": [], "rationale": "Evidence checked"}
        with patch.object(core, "llm", side_effect=fake):
            core.run_job("job")
        result = core.get("job", "job")
        self.assertEqual([t["status"] for t in result["tasks"]], ["committed", "disputed"])
        self.assertEqual(core.paper()["number"], self.version["number"] + 1)
        core.decide("job", result["tasks"][1]["id"], "reject")
        self.assertEqual(core.paper()["number"], self.version["number"] + 1)
        core.undo()
        self.assertEqual(core.paper()["sections"][1]["blocks"], [])
        self.assertEqual(core.paper()["number"], self.version["number"] + 2)

    def test_markdown_round_trip_and_fenced_headings(self):
        text = "# Notes\n\nOpening **argument**.\n\n## Implementation\n\n1. Start\n2. Finish\n\n```md\n## Not a section\n```\n"
        version = core.save_markdown(text, self.version["id"])
        self.assertEqual(len(version["sections"]), 2)
        self.assertEqual(core.markdown(version), text)
        self.assertEqual(core.get("version", self.version["id"]), self.version)

    def test_stale_manual_save_does_not_overwrite_new_document(self):
        core.save_markdown("# New draft", self.version["id"])
        with self.assertRaisesRegex(ValueError, "document changed"):
            core.save_markdown("# Stale draft", self.version["id"])
        self.assertEqual(core.paper()["title"], "New draft")

    def test_unchanged_markdown_preserves_block_ids_and_claims(self):
        section = self.version["sections"][1]
        section["blocks"] = [{"id": "block", "text": "Existing text", "claims": [{"text": "claim"}]}]
        core.put("version", self.version)
        saved = core.save_markdown(core.markdown(self.version), self.version["id"])
        self.assertEqual(saved["sections"][1], section)

    def test_selection_checks_version_offsets_and_surrounding_text(self):
        version = core.save_markdown("# Notes\n\n## Intro\n\nBefore. Rephrase me. After.", self.version["id"])
        section = version["sections"][0]
        selection = {"version_id": version["id"], "section_id": section["id"],
                     "block_id": section["blocks"][0]["id"], "start": 8, "end": 20, "text": "Rephrase me."}
        core.validate_selection(selection, version)
        proposal = {"operation": "replace_block", "block_id": selection["block_id"], "text": "Before. Revised. After."}
        self.assertIsNone(core.validate_selection_proposal(proposal, selection, section))
        proposal["text"] = "Other content."
        self.assertIn("outside", core.validate_selection_proposal(proposal, selection, section))
        with self.assertRaisesRegex(ValueError, "document changed"):
            core.validate_selection(selection, self.version)

    def test_stale_review_cannot_overwrite_manual_edit(self):
        section = self.version["sections"][1]
        task = {"id": "task", "section_id": section["id"], "base_section": section,
                "proposal": {"section_id": section["id"], "operation": "append", "text": "Old proposal", "claims": []}}
        job = {"id": "job", "prompt": "edit", "tasks": [task]}
        saved = core.save_markdown("# Test paper\n\n## Introduction\n\nHuman revision", self.version["id"])
        self.assertFalse(core.commit(task, job))
        self.assertEqual(core.paper(), saved)
        self.assertEqual(task["status"], "blocked")

    def test_new_section_and_inquiry_with_full_document(self):
        job = {"id": "job", "prompt": "Add implementation", "status": "queued", "tasks": []}
        core.put("job", job)
        def fake(role, system, payload):
            if role == "planner":
                self.assertIn("document", payload)
                return {"tasks": [{"section_id": None, "heading": "Implementation", "instruction": "Add steps", "change_requested": True}]}
            if role == "writer":
                return {"section_id": payload["section"]["id"], "operation": "append", "text": "1. Gather notes\n2. Review", "claims": []}
            if role == "evidence": return {"unsupported_claims": [], "objections": []}
            return {"objections": []}
        with patch.object(core, "llm", side_effect=fake): core.run_job("job")
        self.assertEqual(core.get("job", "job")["tasks"][0]["status"], "committed")
        self.assertEqual(core.paper()["sections"][-1]["heading"], "Implementation")
        before = core.paper()
        job = {"id": "inquiry", "prompt": "Challenge this", "status": "queued", "tasks": []}
        core.put("job", job)
        def inquire(role, system, payload):
            self.assertEqual(payload["document"]["id"], before["id"])
            if role == "planner": return {"tasks": [{"section_id": None, "instruction": "Challenge this", "change_requested": False}]}
            return {"finding": "Consider alternatives"}
        with patch.object(core, "llm", side_effect=inquire): core.run_job("inquiry")
        self.assertEqual(core.get("job", "inquiry")["status"], "complete")
        self.assertEqual(core.paper(), before)


if __name__ == "__main__":
    unittest.main()
