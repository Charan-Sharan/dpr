import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core


TITLE = "Can prompt engineering be a career option?"


class WritingIntentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = patch.object(core, "DB", Path(temporary.name) / "test.db")
        database.start()
        self.addCleanup(database.stop)
        self.before = core.paper()

    def job(self, prompt):
        job = {"id": core.uid(), "prompt": prompt, "tasks": [], "status": "queued"}
        core.put("job", job)
        return job

    def test_title_updates_document_without_writer_or_evidence_calls(self):
        job = self.job("Lets work on a papper titled " + TITLE)
        plan = {"tasks": [{"operation": "set_title", "title": TITLE, "section_id": None,
                           "change_requested": True}]}
        with patch.object(core, "llm", return_value=plan) as model:
            core.run_job(job["id"])
        self.assertEqual(model.call_count, 1)
        self.assertEqual(core.paper()["title"], TITLE)
        self.assertEqual(core.paper()["sections"], [])
        self.assertEqual(core.paper()["number"], self.before["number"] + 1)
        result = core.get("job", job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertIn("1 document change", result["summary"])
        core.undo()
        self.assertEqual(core.paper()["title"], self.before["title"])

    def test_followup_uses_history_and_latest_title_for_provisional_abstract(self):
        prior = self.job('We will work on the project titled "' + TITLE + '"')
        prior["status"] = "error"
        core.put("job", prior)
        job = self.job("Update the title and also fill the abstract keep it clear and concise")
        def model(role, system, payload):
            if role == "planner":
                self.assertIn(TITLE, payload["recent_requests"][0]["prompt"])
                return {"tasks": [
                    {"operation": "set_title", "title": TITLE, "instruction": "Set title", "section_id": None},
                    {"operation": "revise_section", "instruction": "Draft abstract", "heading": "Abstract", "section_id": None, "depends_on": [0]}]}
            self.assertEqual(payload["document"]["title"], TITLE)
            self.assertIn("prospective", system)
            if role == "writer":
                return {"section_id": payload["section"]["id"], "operation": "append", "claims": [],
                        "text": "This paper will examine whether prompt engineering could form a sustainable career, focusing on skills, evaluation, and the evidence needed to assess opportunities.",
                        "rationale": "Added the requested abstract."}
            self.assertNotIn("proposal", payload)
            self.assertNotIn("rationale", payload)
            return {"objections": [], "unsupported_claims": []}
        with patch.object(core, "llm", side_effect=model):
            core.run_job(job["id"])
        self.assertEqual(core.get("job", job["id"])["status"], "complete")
        self.assertEqual(core.paper()["title"], TITLE)
        self.assertEqual(core.paper()["sections"][0]["heading"], "Abstract")
        self.assertIn("will examine", core.markdown(core.paper()))

    def test_missing_results_asks_for_input_without_inserting_placeholder(self):
        job = self.job("Summarize my experiment's measured results")
        def model(role, system, payload):
            if role == "planner":
                return {"tasks": [{"operation": "revise_section", "section_id": None, "heading": "Results", "instruction": "Summarize measured results"}]}
            return {"needs_input": "Please provide the measurements and experimental conditions."}
        with patch.object(core, "llm", side_effect=model):
            core.run_job(job["id"])
        result = core.get("job", job["id"])
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["tasks"][0]["status"], "needs_input")
        self.assertIn("No document changes saved", result["summary"])
        self.assertEqual(core.paper(), self.before)

    def test_title_cannot_overwrite_concurrent_human_title(self):
        job = self.job("Rename title")
        task = {"id": "title", "title": TITLE, "base_title": self.before["title"]}
        job["tasks"] = [task]
        newer = core.save_markdown("# Human's newer title", self.before["id"])
        self.assertFalse(core.commit_title(task, job))
        self.assertEqual(core.paper(), newer)
        self.assertEqual(task["status"], "blocked")

    def test_inquiry_about_titles_does_not_change_document(self):
        job = self.job("What do you think of this title?")
        with patch.object(core, "llm", side_effect=[
            {"tasks": [{"operation": "inquiry", "section_id": None, "instruction": "Discuss the title"}]},
            {"finding": "A more specific title could clarify the scope."}]):
            core.run_job(job["id"])
        self.assertEqual(core.paper(), self.before)
        self.assertEqual(core.get("job", job["id"])["summary"], "Inquiry answered; document unchanged.")

    def test_fabricated_result_remains_blocked_without_sources(self):
        job = self.job("Draft an abstract")
        def model(role, system, payload):
            if role == "planner":
                return {"tasks": [{"operation": "revise_section", "section_id": None, "heading": "Abstract", "instruction": "Draft abstract"}]}
            if role == "writer":
                return {"section_id": payload["section"]["id"], "operation": "append", "claims": [], "text": "Our survey found that 90% of employers hire prompt engineers."}
            if role == "evidence":
                return {"unsupported_claims": ["No survey data supports the 90% figure."], "objections": []}
            return {"objections": []}
        with patch.object(core, "llm", side_effect=model):
            core.run_job(job["id"])
        self.assertEqual(core.paper(), self.before)
        result = core.get("job", job["id"])
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["tasks"][0]["status"], "evidence_required")

    def test_writer_repairs_review_objection_and_revision_is_audited_again(self):
        job = self.job("Draft an abstract about prompt engineering careers")
        writes, audits = [], []
        def model(role, system, payload):
            if role == "planner":
                return {"tasks": [{"operation": "revise_section", "section_id": None, "heading": "Abstract", "instruction": "Draft abstract"}]}
            if role == "writer":
                writes.append(payload)
                if len(writes) == 2:
                    self.assertEqual(payload["review_feedback"]["audit"]["unsupported_claims"], ["Unsupported claim about growth"])
                text = "The field is rapidly growing." if len(writes) == 1 else "This paper will examine possible career paths and the evidence needed to evaluate them."
                return {"section_id": payload["section"]["id"], "operation": "append", "text": text, "claims": []}
            if role == "evidence":
                audits.append(payload)
                return {"unsupported_claims": ["Unsupported claim about growth"] if len(audits) == 1 else [], "objections": []}
            return {"objections": []}
        with patch.object(core, "llm", side_effect=model):
            core.run_job(job["id"])
        self.assertEqual(len(writes), 2)
        self.assertEqual(len(audits), 2)
        self.assertNotIn("rapidly growing", core.markdown(core.paper()))
        self.assertIn("will examine", core.markdown(core.paper()))
        self.assertEqual(core.get("job", job["id"])["status"], "complete")

    def test_move_literature_survey_after_introduction_without_model_or_text_changes(self):
        document = core.save_markdown("# Paper\n\n## Introduction\n\nIntro text.\n\n## Results\n\nResults text.\n\n## Literature Survey\n\nSurvey with **references**.\n\n## References\n\n- Citation", self.before["id"])
        original_sections = {section["id"]: section for section in document["sections"]}
        job = self.job("Move the literature Surevy from bottom to after Introduction")
        with patch.object(core, "llm") as model:
            core.run_job(job["id"])
        model.assert_not_called()
        result = core.get("job", job["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["tasks"][0]["operation"], "move_section")
        self.assertEqual([s["heading"] for s in core.paper()["sections"]],
                         ["Introduction", "Literature Survey", "Results", "References"])
        for section in core.paper()["sections"]:
            self.assertEqual(section, original_sections[section["id"]])
        core.undo()
        self.assertEqual([s["heading"] for s in core.paper()["sections"]],
                         ["Introduction", "Results", "Literature Survey", "References"])

    def test_new_section_respects_requested_position(self):
        core.save_markdown("# Paper\n\n## Introduction\n\nOpening.\n\n## References\n\n- Citation", self.before["id"])
        job = self.job("Add a Literature Survey section after Introduction, not at the bottom")
        def model(role, system, payload):
            if role == "planner":
                return {"tasks": [{"operation": "revise_section", "section_id": None, "heading": "Literature Survey",
                                   "instruction": "Create literature survey"}]}
            if role == "writer":
                return {"section_id": payload["section"]["id"], "operation": "append", "text": "This section will review relevant work.", "claims": []}
            return {"objections": [], "unsupported_claims": []}
        with patch.object(core, "llm", side_effect=model):
            core.run_job(job["id"])
        self.assertEqual(core.get("job", job["id"])["status"], "complete")
        self.assertEqual([s["heading"] for s in core.paper()["sections"]],
                         ["Introduction", "Literature Survey", "References"])

    def test_move_to_end_and_ambiguous_move(self):
        core.save_markdown("# Paper\n\n## References\n\n- Citation\n\n## Discussion\n\nDiscussion.", self.before["id"])
        job = self.job("Move References to the bottom")
        with patch.object(core, "llm") as model:
            core.run_job(job["id"])
        model.assert_not_called()
        self.assertEqual([s["heading"] for s in core.paper()["sections"]], ["Discussion", "References"])
        before = core.paper()
        job = self.job("Move an unknown section after Discussion")
        with patch.object(core, "llm") as model:
            core.run_job(job["id"])
        model.assert_not_called()
        self.assertEqual(core.paper(), before)
        self.assertEqual(core.get("job", job["id"])["status"], "needs_attention")

    def test_large_source_is_bounded_for_model_and_full_text_validates_quotes(self):
        source = {"id": "large", "title": "Notes", "text": "Background. " * 7000 + "The survey reports a final observation."}
        excerpt = core.model_sources([source], "survey observation")[0]
        self.assertLessEqual(len(excerpt["text"]), 4500)
        self.assertIn("survey reports", excerpt["text"])
        section = {"id": "section", "heading": "Literature Survey", "blocks": []}
        proposal = {"section_id": "section", "operation": "append", "text": "A final observation is reported.",
                    "claims": [{"text": "Final observation", "citations": [{"source_id": "large", "quote": "The survey reports a final observation."}]}]}
        self.assertIsNone(core.validate_proposal(proposal, section, [source]))

    def evidence_task(self):
        section = {"id": "new-section", "heading": "Abstract", "blocks": []}
        task = {"id": "task", "status": "evidence_required", "instruction": "Add abstract", "section_id": section["id"],
                "new_section": True, "heading": section["heading"], "base_section": None, "reason": "No supporting source",
                "proposal": {"section_id": section["id"], "operation": "append", "text": "A claim the author accepts.",
                             "claims": [{"text": "A claim", "citations": []}]}}
        job = self.job("Add abstract")
        job.update(status="needs_attention", tasks=[task])
        core.put("job", job)
        return job, task

    def test_allow_evidence_override_saves_version_audit_and_can_undo(self):
        job, task = self.evidence_task()
        result = core.decide(job["id"], task["id"], "allow")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["tasks"][0]["status"], "committed")
        block = core.paper()["sections"][0]["blocks"][0]
        self.assertEqual(block["text"], task["proposal"]["text"])
        self.assertEqual(block["evidence_override"]["reason"], "No supporting source")
        self.assertEqual(block["evidence_override"], result["tasks"][0]["evidence_override"])
        self.assertEqual(core.all_items("event")[-1]["role"], "researcher")
        with self.assertRaisesRegex(ValueError, "not awaiting"):
            core.decide(job["id"], task["id"], "allow")
        core.undo()
        self.assertEqual(core.paper()["sections"], [])

    def test_allow_does_not_bypass_invalid_operation_or_stale_section(self):
        for stale in (False, True):
            job, task = self.evidence_task()
            if stale:
                task["base_section"] = {"id": "old-section"}
            else:
                task["proposal"]["operation"] = "delete_document"
            core.put("job", job)
            with self.assertRaises(ValueError):
                core.decide(job["id"], task["id"], "allow")
            self.assertEqual(core.paper(), self.before)

    def test_evidence_revision_can_be_rejected_but_not_implicitly_approved(self):
        job, task = self.evidence_task()
        with self.assertRaises(ValueError):
            core.decide(job["id"], task["id"], "approve")
        core.decide(job["id"], task["id"], "reject")
        self.assertEqual(core.paper(), self.before)
        self.assertEqual(core.get("job", job["id"])["tasks"][0]["status"], "rejected")
