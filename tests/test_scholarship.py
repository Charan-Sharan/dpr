import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import providers
import scholarship as s


class ScholarshipTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = patch.object(core, "DB", Path(directory.name) / "test.sqlite3")
        database.start()
        self.addCleanup(database.stop)
        env = patch.dict(os.environ, {"GROQ_API_KEY": "test-only", "OPEN_ROUTER_API_KEY": "test-only"})
        env.start()
        self.addCleanup(env.stop)
        core.ensure_projects()
        self.version = core.save_markdown("# Paper\n\n## Introduction\n\nOriginal prose.\n\n## Methods\n\nProspective methods.\n", core.paper()["id"])
        s.settings(True)
        self.calls = []
        self.unsupported = False
        self.dependencies = False
        model = patch.object(providers, "complete", side_effect=self.model)
        model.start()
        self.addCleanup(model.stop)

    def model(self, provider, role, system, payload, **kwargs):
        self.calls.append((provider, role, system, copy.deepcopy(payload), kwargs))
        if "Break the user's instruction" in system:
            tasks = [{"operation": "revise_section", "section_id": self.version["sections"][0]["id"], "instruction": "Revise introduction", "depends_on": []}]
            if self.dependencies:
                tasks.append({"operation": "revise_section", "section_id": self.version["sections"][1]["id"], "instruction": "Revise methods", "depends_on": [0]})
            return {"tasks": tasks}
        if "Classify the request" in system:
            return {"mode": "discuss"}
        if "hand_raise:boolean" in system:
            return {"hand_raise": True, "priority": 2, "confidence": .7, "pointer": "Investigate competing explanations from " + payload["perspective"], "relevant": True}
        if "block_id:null|string,text,claims" in system:
            return {"section_id": payload["section"]["id"], "operation": "replace_section", "text": "A proposed research scope.",
                    "claims": [{"text": "Unsupported claim", "citations": []}] if self.unsupported else []}
        if "unsupported_claims:[string]" in system:
            return {"unsupported_claims": [], "objections": [], "rationale": "Prospective prose, not an empirical assertion"}
        if "Independently review" in system:
            return {"objections": [], "rationale": "Reviewed wording"}
        if "summary:string" in system:
            return {"summary": "Compare alternatives; evidence is incomplete.", "disagreements": ["Alternative interpretation"], "missing_evidence": ["Measurements needed"], "choices": ["Supply data"]}
        if "Review this passage" in system:
            return {"text": "Check consistency of " + payload["section"], "open_questions": ["Do results support this conclusion?"]}
        return {"text": "Contribution " + str(len(self.calls)) + " from " + payload.get("perspective", "reviewer"),
                "assumptions": ["Unverified assumption"], "alternatives": ["A competing explanation"], "open_questions": ["What evidence would discriminate?"]}

    def run_session(self, mode="discuss"):
        job = s.create("Investigate the topic", mode)
        s.execute(job["id"])
        result = s.get(job["id"])
        self.assertNotEqual(result["status"], "failed", result["activity"][-1])
        return result

    def test_discussion_is_bounded_independent_and_never_edits(self):
        job = self.run_session()
        self.assertEqual(core.paper()["id"], self.version["id"])
        self.assertEqual(job["status"], "awaiting_input")
        self.assertEqual(job["contributions"], 6)
        self.assertLessEqual(job["calls"], 40)
        self.assertEqual(len(set(t["agent_id"] for t in job["turns"])), 3)
        self.assertTrue(all(t["independent"] for t in job["turns"][:3]))
        initial = [call for call in self.calls if "assumptions:[string]" in call[2]][:3]
        self.assertTrue(all(not call[3]["turns"] and not call[3]["memory"] for call in initial))
        self.assertTrue(core.all_items("memory"))
        self.assertEqual([e["seq"] for e in job["activity"]], list(range(1, job["sequence"] + 1)))

    def test_revision_requires_approval_and_is_idempotent(self):
        job = self.run_session("revise")
        self.assertEqual(job["tasks"][0]["status"], "awaiting_approval")
        self.assertEqual(core.paper()["id"], self.version["id"])
        task = job["tasks"][0]
        s.decide(job["id"], task["id"], "approve")
        approved = core.paper()
        self.assertEqual(s.get(job["id"])["status"], "completed")
        self.assertIn("no further action required", s.get(job["id"])["summary"])
        self.assertIn("proposed research scope", core.markdown(approved))
        s.decide(job["id"], task["id"], "approve")
        self.assertEqual(core.paper()["id"], approved["id"])

    def test_override_requires_rationale_and_retains_concern(self):
        self.unsupported = True
        job = self.run_session("revise")
        task = job["tasks"][0]
        self.assertEqual(task["status"], "evidence_required")
        with self.assertRaises(ValueError):
            s.decide(job["id"], task["id"], "allow")
        with self.assertRaises(ValueError):
            s.decide(job["id"], task["id"], "approve")
        s.decide(job["id"], task["id"], "allow", "Retain as an explicitly unverified draft")
        self.assertEqual(s.get(job["id"])["status"], "completed")
        self.assertIn("1 document change(s) saved", s.get(job["id"])["summary"])
        self.assertTrue(core.paper()["sections"][0]["blocks"][0]["evidence_override"])
        self.assertTrue(any(m["kind"] == "open_question" for m in core.all_items("memory")))
        self.assertIn("unverified draft", str(s.audit_export()))

    def test_stale_approval_and_cross_project_lookup_are_blocked(self):
        job = self.run_session("revise")
        core.save_markdown("# Changed paper", core.paper()["id"])
        with self.assertRaisesRegex(ValueError, "Document changed"):
            s.decide(job["id"], job["tasks"][0]["id"], "approve")
        project = core.create_project("Other")
        with core.project_scope(project["id"]):
            with self.assertRaises(ValueError):
                s.get(job["id"])
            self.assertEqual(s.snapshot()["memory"], [])

    def test_late_result_after_stop_is_discarded(self):
        job = s.create("Question", "discuss")
        def late(*args, **kwargs):
            s.control(job["id"], "stop")
            return {"text": "Late contribution"}
        with patch.object(providers, "complete", side_effect=late):
            s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["turns"], [])
        self.assertEqual(core.all_items("memory"), [])

    def test_pause_resume_recovery_and_budget(self):
        job = s.create("Question", "discuss")
        s.control(job["id"], "pause")
        s.execute(job["id"])
        self.assertEqual(len(self.calls), 0)
        s.control(job["id"], "resume")
        s.recover()
        self.assertEqual(s.get(job["id"])["status"], "interrupted")
        with self.assertRaises(ValueError):
            s.control(job["id"], "resume")
        job = s.control(job["id"], "continue", "Reconsider the assumptions")
        job["calls"] = 40
        core.put("job", job)
        s.execute(job["id"])
        self.assertEqual(s.get(job["id"])["status"], "paused")
        self.assertEqual(len(self.calls), 0)

    def test_dependent_task_runs_after_approval(self):
        self.dependencies = True
        job = self.run_session("revise")
        self.assertEqual(job["tasks"][1]["status"], "waiting")
        s.decide(job["id"], job["tasks"][0]["id"], "approve")
        self.assertEqual(s.get(job["id"])["status"], "queued")
        s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(result["tasks"][1]["status"], "awaiting_approval")

    def test_memory_corrections_preserve_history_and_staleness(self):
        job = self.run_session()
        item = s.snapshot()["memory"][0]
        changed = s.update_memory(item["id"], "correct", "Researcher correction")
        self.assertEqual(changed["authority"], "researcher_statement")
        self.assertEqual(changed["history"][0]["text"], item["text"])
        s.update_memory(item["id"], "resolve")
        self.assertEqual(s.update_memory(item["id"], "reopen")["status"], "open")
        core.save_markdown("# Updated", core.paper()["id"])
        self.assertTrue(all(m["stale"] for m in s.snapshot()["memory"]))

    def test_whole_document_review_and_finalization(self):
        job = self.run_session("review")
        self.assertEqual(job["coverage"], [x["id"] for x in self.version["sections"]])
        self.assertEqual(core.paper()["id"], self.version["id"])
        s.control(job["id"], "finalize")
        self.assertEqual(s.get(job["id"])["reviewed_version"], self.version["id"])

    def test_migration_backs_up_once_and_preserves_document(self):
        s.migrate()
        backups = list(core.DB.parent.glob("*.backup-*"))
        self.assertEqual(len(backups), 1)
        s.migrate()
        self.assertEqual(list(core.DB.parent.glob("*.backup-*")), backups)
        self.assertEqual(core.paper()["id"], self.version["id"])

    def test_direct_move_does_not_call_models(self):
        job = s.create("Move Methods before Introduction", "auto")
        s.execute(job["id"])
        self.assertEqual(self.calls, [])
        self.assertEqual(core.paper()["sections"][0]["heading"], "Methods")

    def test_invalid_proposal_cannot_be_allowed(self):
        job = self.run_session("revise")
        job["tasks"][0].update(status="evidence_required", proposal={"section_id": "wrong", "operation": "replace_section", "text": "Wrong target"})
        core.put("job", job)
        with self.assertRaises(ValueError):
            s.decide(job["id"], job["tasks"][0]["id"], "allow", "Override")
        self.assertEqual(core.paper()["id"], self.version["id"])

    def test_panel_changes_only_while_paused(self):
        job = s.create("Question", "discuss")
        with self.assertRaises(ValueError):
            s.control(job["id"], "panel", panel=s.default_panel())
        s.control(job["id"], "pause")
        panel = s.default_panel()
        panel[0]["perspective"] = "Ethics specialist"
        self.assertEqual(s.control(job["id"], "panel", panel=panel)["panel"][0]["perspective"], "Ethics specialist")

    def test_rejected_dependency_does_not_run(self):
        self.dependencies = True
        job = self.run_session("revise")
        s.decide(job["id"], job["tasks"][0]["id"], "reject")
        result = s.get(job["id"])
        self.assertEqual(result["status"], "awaiting_input")
        self.assertEqual(result["tasks"][1]["status"], "waiting")

    def test_reply_at_limit_is_saved_without_new_calls(self):
        job = self.run_session()
        count = len(self.calls)
        result = s.control(job["id"], "turn", "I disagree with the assumption", reply_to=job["turns"][0]["id"])
        self.assertEqual(result["status"], "awaiting_input")
        self.assertEqual(result["turns"][-1]["reply_to"], job["turns"][0]["id"])
        s.execute(job["id"])
        self.assertEqual(len(self.calls), count)

    def test_oversized_retry_and_fallback_count_every_attempt(self):
        job = s.create("Question", "discuss")
        job["status"] = "running"
        core.put("job", job)
        payloads = []
        def transport(provider, role, system, payload, **kwargs):
            payloads.append(copy.deepcopy(payload))
            if len(payloads) == 1:
                raise providers.ProviderError("HTTP 413 request too large")
            if len(payloads) == 2:
                raise providers.ProviderError("HTTP 403 denied")
            return {"text": "Fallback"}
        with patch.object(providers, "complete", side_effect=transport):
            result = s.model_call(job, "writer", "Explain", {"source": "x" * 4000})
        self.assertEqual(result["text"], "Fallback")
        self.assertLess(len(payloads[1]["source"]), len(payloads[0]["source"]))
        self.assertEqual(s.get(job["id"])["calls"], 3)

    def test_redirect_discards_late_old_generation(self):
        job = s.create("Old objective", "discuss")
        def late(*args, **kwargs):
            s.control(job["id"], "redirect", "New objective")
            return {"text": "Stale answer"}
        with patch.object(providers, "complete", side_effect=late):
            s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["objective"], "New objective")
        self.assertFalse(any(t["text"] == "Stale answer" for t in result["turns"]))

    def test_review_covers_every_chunk_and_synthesis_batch(self):
        self.version = core.save_markdown("# Long paper\n\n" + "\n\n".join("## Section " + str(i) + "\n\n" + ("Passage " + str(i) + ". ") * 600 for i in range(7)), core.paper()["id"])
        job = self.run_session("review")
        self.assertEqual(len(job["coverage"]), 7)
        self.assertTrue(job["synthesis_complete"])
        passages = [c[3]["passage"] for c in self.calls if "Review this passage" in c[2]]
        original = "".join("\n\n".join(b["text"] for b in section["blocks"]) for section in self.version["sections"])
        self.assertEqual("".join(passages), original)
        findings = [t for t in job["turns"] if t.get("section_id")]
        self.assertEqual(job["synthesis_index"], len(findings))

    def test_partial_review_resumes_after_call_budget(self):
        self.version = core.save_markdown("# Large\n\n" + "\n\n".join("## Section " + str(i) + "\n\nText" for i in range(42)), core.paper()["id"])
        job = self.run_session("review")
        self.assertEqual(job["status"], "paused")
        self.assertEqual(job["calls"], 40)
        self.assertEqual(len(job["coverage"]), 40)
        self.assertNotIn("checkpoint", job)
        with self.assertRaises(ValueError):
            s.control(job["id"], "finalize")
        s.control(job["id"], "continue", "Finish the remaining review")
        s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(len(result["coverage"]), 42)
        self.assertTrue(result["synthesis_complete"])

    def test_invalid_panel_recommendation_falls_back_visibly(self):
        job = s.create("Question", "discuss")
        s.control(job["id"], "pause")
        s.control(job["id"], "recommend_panel")
        s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(result["status"], "paused")
        self.assertEqual(len(result["panel"]), 3)
        self.assertTrue(any("selector fallback" in e["message"] for e in result["activity"]))

    def test_new_review_required_after_document_changes(self):
        job = self.run_session("review")
        updated = core.save_markdown("# Changed\n\n## New section\n\nNew text", core.paper()["id"])
        with self.assertRaises(ValueError):
            s.control(job["id"], "finalize")
        s.control(job["id"], "continue", "Review the new draft")
        s.execute(job["id"])
        result = s.get(job["id"])
        self.assertEqual(result["review_version"], updated["id"])
        self.assertEqual(result["coverage"], [updated["sections"][0]["id"]])

    def test_old_committed_session_is_displayed_complete_without_rewriting_history(self):
        job = self.run_session("revise")
        s.decide(job["id"], job["tasks"][0]["id"], "approve")
        stored = s.get(job["id"])
        stored.update(status="awaiting_input", summary="Review proposals and unresolved questions; only approved prose is saved.")
        core.put("job", stored)
        version = core.paper()["id"]
        displayed = s.snapshot()["sessions"][-1]
        self.assertEqual(displayed["status"], "completed")
        self.assertIn("no further action required", displayed["summary"])
        self.assertEqual(s.get(job["id"]), stored)
        self.assertEqual(core.paper()["id"], version)

    def test_rejecting_last_proposal_completes_without_document_change(self):
        job = self.run_session("revise")
        result = s.decide(job["id"], job["tasks"][0]["id"], "reject")
        self.assertEqual(result["status"], "completed")
        self.assertIn("No document changes saved", result["summary"])
        self.assertEqual(core.paper()["id"], self.version["id"])

    def test_waiting_summary_explains_actual_action(self):
        job = dict(tasks=[dict(status="needs_input", reason="Please supply the observed measurements")])
        s.revision_outcome(job)
        self.assertEqual(job["status"], "awaiting_input")
        self.assertIn("Please supply the observed measurements", job["summary"])


if __name__ == "__main__":
    unittest.main()
