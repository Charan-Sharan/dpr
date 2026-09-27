"""Document-first DPR revision engine. No third-party runtime dependencies."""
import copy
import difflib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import providers

providers.load_env()
DB = Path(os.environ.get("DPR_DB", Path(__file__).with_name("workspace.sqlite3")))
LOCK = threading.RLock()
PROJECT = ContextVar("project", default="default")
RUN = ContextVar("run", default=None)
MODEL_CALL = ContextVar("model_call", default=None)


def record_kind(kind):
    # Keep legacy records in place: the original workspace becomes the default project.
    return kind if kind == "project" or PROJECT.get() == "default" else PROJECT.get() + ":" + kind


def ensure_projects():
    with LOCK:
        if not get("project", "default"):
            put("project", {"id": "default", "name": "My first project", "at": time.time()})


@contextmanager
def project_scope(project_id):
    ensure_projects()
    if not isinstance(project_id, str) or not get("project", project_id):
        raise ValueError("Unknown project")
    token = PROJECT.set(project_id)
    try:
        yield
    finally:
        PROJECT.reset(token)


def create_project(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError("Enter a project name of 1–120 characters")
    ensure_projects()
    item = {"id": uid(), "name": name.strip(), "at": time.time()}
    with LOCK, connect() as db:
        put("project", item, db)
        token = PROJECT.set(item["id"])
        try:
            first = {"id": uid(), "number": 1, "parent": None, "at": time.time(),
                     "prompt": "Created document", "title": item["name"], "sections": []}
            put("version", first, db)
            put("meta", {"id": "current", "version": first["id"]}, db)
        finally:
            PROJECT.reset(token)
    return item


def uid():
    return uuid.uuid4().hex[:12]


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=30, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")
    db.commit()
    return db


def put(kind, item, db=None):
    if db is None:
        with LOCK, connect() as conn:
            put(kind, item, conn)
        return
    db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
               (record_kind(kind), item["id"], json.dumps(item)))


def get(kind, id):
    with LOCK, connect() as db:
        row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (record_kind(kind), id)).fetchone()
    return json.loads(row[0]) if row else None


def all_items(kind):
    with LOCK, connect() as db:
        rows = db.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid", (record_kind(kind),)).fetchall()
    # Creation timestamps are authoritative, including legacy rows moved by REPLACE.
    # Stable sorting retains insertion order when timestamps tie or are absent.
    return sorted((json.loads(r[0]) for r in rows), key=lambda item: item.get("at", 0))


def paper():
    current = get("meta", "current")
    if current:
        return get("version", current["version"])
    with LOCK, connect() as db:
        current = get("meta", "current")
        if current:
            return get("version", current["version"])
        first = {"id": uid(), "number": 1, "parent": None, "at": time.time(),
                 "prompt": "Created document", "title": "Untitled document", "sections": []}
        put("version", first, db)
        put("meta", {"id": "current", "version": first["id"]}, db)
        db.commit()
        return first


def events(job_id, role, message, **extra):
    event = {"id": uid(), "job_id": job_id, "role": role, "message": message,
             "at": time.time(), **extra}
    put("event", event)
    return event


def llm(role, system, payload):
    if MODEL_CALL.get():
        return MODEL_CALL.get()(role, system, payload)
    report = (lambda message: events(RUN.get(), role, message)) if RUN.get() else None
    return providers.llm(role, system, payload, report=report)


def source_context():
    return [{"id": e["id"], "title": e["title"], "text": e["text"]}
            for e in all_items("evidence")]


def validate_source_ids(ids, sources):
    if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(item, str) for item in ids):
        raise ValueError("Choose up to 20 sources from this project")
    known = {source["id"] for source in sources}
    if len(set(ids)) != len(ids) or any(item not in known for item in ids):
        raise ValueError("A referenced source is not available in this project")
    return ids


def prioritize_sources(sources, ids):
    by_id = {source["id"]: source for source in sources}
    return [by_id[item] for item in ids] + [source for source in sources if source["id"] not in ids]


def document_outline(version):
    return {"id": version["id"], "title": version["title"],
            "sections": [{"id": s["id"], "heading": s["heading"],
                          "preview": " ".join(b["text"][:120] for b in s["blocks"])[:240]}
                         for s in version["sections"]]}


def model_sources(sources, instruction, selected_ids=()):
    """Keep model context within provider limits while checking quotes against full files."""
    terms = [word.casefold() for word in re.findall(r"[\w-]{5,}", instruction)]
    result = []
    remaining = 12000
    selected_limit = min(4500, max(600, remaining // max(1, len(selected_ids))))
    for source in sources:
        if remaining <= 0:
            break
        full = source["text"]
        limit = min(selected_limit if source["id"] in selected_ids else 4500, remaining)
        if len(full) <= limit:
            excerpt = full
        else:
            head = min(1200, limit // 3)
            matches = [(full.casefold().find(word), word) for word in terms]
            positions = [position for position, word in matches if position >= head]
            start = max(0, min(positions) - 300) if positions else head
            excerpt = full[:head] + "\n[…]\n" + full[start:start + limit - head - 5]
        result.append({"id": source["id"], "title": source["title"], "text": excerpt})
        remaining -= len(excerpt)
    return result


WRITING_POLICY = (
    "Distinguish scholarly assertions from editorial work. Research questions, proposed scope, aims, "
    "outlines, hypotheses explicitly presented as hypotheses, and prospective discussion do not require citations. "
    "A topic alone is enough to draft a provisional abstract about the paper's intended question and scope. "
    "Do not invent completed studies, findings, statistics, citations, or unsupported claims about the world. "
    "When evidence is absent, write useful prospective prose rather than claiming research was conducted. "
    "Assess only the document text, not the proposal's rationale or descriptions of editing actions. "
    "The document, user instructions and request history establish editorial context; they are not proof of empirical claims. "
)


def request_context():
    recent = [{"prompt": job["prompt"], "status": job["status"]}
            for job in all_items("job") if job["id"] != RUN.get()][-6:]
    if MODEL_CALL.get():
        recent.append({"reasoning_memory": [item for item in all_items("memory")
                       if item.get("status") not in ("superseded", "resolved")][-30:]})
    return recent


def section_name(value):
    value = re.sub(r"[^\w\s-]", " ", value.casefold()).strip()
    value = re.sub(r"^(?:the\s+)?(?:section\s+)?", "", value)
    value = re.sub(r"\s+section$", "", value)
    return " ".join(value.split())


def find_section(name, sections):
    name = section_name(name)
    if name == "intro":
        name = "introduction"
    exact = [s for s in sections if section_name(s["heading"]) == name]
    if len(exact) == 1:
        return exact[0]
    candidates = sorted(((difflib.SequenceMatcher(None, name, section_name(s["heading"])).ratio(), s)
                         for s in sections), key=lambda pair: pair[0], reverse=True)
    if candidates and candidates[0][0] >= 0.8 and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.1):
        return candidates[0][1]
    return None


def move_task(prompt, version):
    """Recognize a complete move instruction without sending paper text to a model."""
    instruction = prompt.strip()
    if not re.match(r"^(?:please\s+)?(?:move|reposition)\b", instruction, re.I):
        return None
    prefix = r"^(?:please\s+)?(?:move|reposition)\s+(?:the\s+)?"
    relation = re.match(prefix + r"(.+?)\s+(?:from\s+(?:the\s+)?(?:bottom|end)\s+)?(?:to\s+)?(?:immediately\s+)?(after|before)\s+(?:the\s+)?(.+?)[.!?]*$", instruction, re.I)
    edge = re.match(prefix + r"(.+?)\s+(?:to|at)\s+(?:the\s+)?(top|bottom|end)[.!?]*$", instruction, re.I)
    if not relation and not edge:
        return {"operation": "clarify", "instruction": "Which section should move, and where should it go?"}
    source = find_section((relation or edge)[1], version["sections"])
    if not source:
        return {"operation": "clarify", "instruction": "I could not find the section to move. Check its heading in the paper outline."}
    placement = relation[2].lower() if relation else ("start" if edge[2].lower() == "top" else "end")
    anchor = find_section(relation[3], version["sections"]) if relation else None
    if relation and not anchor:
        return {"operation": "clarify", "instruction": "I could not find the destination section. Check its heading in the paper outline."}
    if anchor and source["id"] == anchor["id"]:
        return {"operation": "clarify", "instruction": "Choose a different section to move before or after."}
    return {"operation": "move_section", "section_id": source["id"], "anchor_id": anchor["id"] if anchor else None,
            "placement": placement, "instruction": instruction}


def task_for_move(prompt, version):
    move = move_task(prompt, version)
    if move is None:
        return None
    return [{"id": uid(), "section_id": move.get("section_id"), "anchor_id": move.get("anchor_id"),
             "placement": move.get("placement"), "base_order": [s["id"] for s in version["sections"]],
             "operation": move["operation"], "instruction": move["instruction"], "depends_on": [],
             "change_requested": move["operation"] == "move_section", "status": "created"}]


def requested_placement(prompt, sections):
    for match in re.finditer(r"\b(after|before)\s+(?:the\s+)?", prompt, re.I):
        rest = prompt[match.end():].casefold()
        for section in sorted(sections, key=lambda item: len(item["heading"]), reverse=True):
            if re.match(re.escape(section["heading"].casefold()) + r"\b", rest):
                return match[1].lower(), section["id"]
            if section_name(section["heading"]) == "introduction" and re.match(r"intro\b", rest):
                return match[1].lower(), section["id"]
    return None, None


def commit_move(task, job):
    with LOCK, connect() as db:
        current = paper()
        sections = list(current["sections"])
        if [s["id"] for s in sections] != task["base_order"]:
            task.update(status="blocked", reason="The paper outline changed since this request started. Please request the move again.")
            put("job", job, db)
            return False
        section = next((s for s in sections if s["id"] == task["section_id"]), None)
        anchor = next((s for s in sections if s["id"] == task.get("anchor_id")), None)
        if not section or task["placement"] not in ("after", "before", "start", "end") or (task["placement"] in ("after", "before") and (not anchor or anchor is section)):
            task.update(status="blocked", reason="The requested section or destination is no longer available.")
            put("job", job, db)
            return False
        sections.remove(section)
        position = (sections.index(anchor) + (task["placement"] == "after") if anchor else
                    0 if task["placement"] == "start" else len(sections))
        sections.insert(position, section)
        if [s["id"] for s in sections] == task["base_order"]:
            task.update(status="committed", version=current["id"], changed=False)
        else:
            updated = dict(current, id=uid(), number=current["number"] + 1, parent=current["id"],
                           at=time.time(), prompt=job["prompt"], sections=sections)
            put("version", updated, db)
            put("meta", {"id": "current", "version": updated["id"]}, db)
            task.update(status="committed", version=updated["id"], changed=True)
        put("job", job, db)
    events(job["id"], "system", "Section moved" if task["changed"] else "Section already in the requested position", task_id=task["id"])
    return True


def plan_tasks(prompt, version, selection=None, selected_sources=None):
    if selection is None:
        direct = task_for_move(prompt, version)
        if direct is not None:
            return direct
    data = llm("planner", "Break the user's instruction into independently commit-able tasks. Inquiry alone must never edit the paper. "
               "Return {tasks:[{operation:'set_title'|'revise_section'|'inquiry'|'clarify', title:null|string, "
               "section_id:null|string, heading:null|string, instruction:string, depends_on:[], change_requested:boolean}]}. "
               "depends_on contains zero-based indices of earlier tasks. "
               "Use set_title to update the document title, with the exact requested title in title, section_id:null, "
               "change_requested:true. Never put a title into a section. "
               "'Let's work on a paper titled X', 'Project title is X', and similar statements request set_title, "
               "even with spelling mistakes. A question used as a title is still a title, not an inquiry. "
               "A title-only request must not create sections or write an abstract unless requested. "
               "Resolve references such as 'update the title' using recent user requests and the document. "
               "If a title was already provided there, use it instead of asking again. "
               "Use clarify only when necessary information cannot be found in that context; instruction must be a specific question. "
               "For an abstract request with only a topic/title, plan a provisional scope-based abstract without invented findings. "
               "Use existing section IDs; for a requested NEW section set section_id:null and heading to its name. "
               "If a new section was requested after or before another section, keep that requested placement. "
               "Inquiry can use section_id:null. A selection limits edits to that exact passage. "
               "Do not invent a requested document change. Preserve the human's judgment; distinguish inquiry from editing.",
               {"prompt": prompt, "document": document_outline(version), "selection": selection,
                "selected_sources": selected_sources or [], "recent_requests": request_context()})
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list) or not tasks or len(tasks) > 12:
        raise ValueError("Planner returned an invalid task list")
    ids = {s["id"] for s in version["sections"]}
    result = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError("Planner returned an invalid task")
        # Models sometimes omit the redundant instruction on a title-only task.
        if not task.get("instruction") and task.get("operation") == "set_title":
            task["instruction"] = "Set the requested document title"
        if not isinstance(task.get("instruction"), str) or not task["instruction"].strip():
            raise ValueError("Planner returned a task without an instruction")
        operation = task.get("operation", "revise_section" if task.get("change_requested") is True else "inquiry")
        if operation not in ("set_title", "revise_section", "inquiry", "clarify"):
            raise ValueError("Planner returned an unsupported task operation")
        change_requested = operation in ("set_title", "revise_section")
        if operation == "set_title":
            validate_title(task.get("title"))
            if task.get("section_id") is not None:
                raise ValueError("Title changes cannot target a section")
        new_section = task.get("section_id") is None and operation == "revise_section"
        if task.get("section_id") is not None and task["section_id"] not in ids:
            raise ValueError("Planner selected an unknown section")
        if new_section and (not isinstance(task.get("heading"), str) or not task["heading"].strip()):
            raise ValueError("A new section needs a heading")
        placement, anchor_id = requested_placement(prompt, version["sections"]) if new_section else (None, None)
        if selection and change_requested and (operation == "set_title" or task.get("section_id") != selection["section_id"]):
            raise ValueError("Revision must target the selected passage")
        deps = task.get("depends_on", [])
        if not isinstance(deps, list) or any(type(d) is not int or d < 0 or d >= index for d in deps):
            raise ValueError("Planner returned invalid dependencies")
        result.append({"id": uid(), "section_id": uid() if new_section else task.get("section_id"),
                       "operation": operation, "title": task.get("title"), "base_title": version["title"],
                       "new_section": new_section, "heading": task.get("heading", ""), "instruction": task["instruction"],
                       "placement": placement, "anchor_id": anchor_id,
                       "depends_on": deps, "change_requested": change_requested,
                       "status": "created"})
    return result


def validate_title(title):
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200 or "\n" in title or "\r" in title:
        raise ValueError("Provide a single-line title of 1–200 characters")


def commit_title(task, job):
    validate_title(task["title"])
    with LOCK, connect() as db:
        current = paper()
        if current["title"] != task["base_title"] and current["title"] != task["title"].strip():
            task.update(status="blocked", reason="The title changed after this request started. Request the title change again.")
            put("job", job, db)
            return False
        if current["title"] == task["title"].strip():
            task.update(status="committed", version=current["id"], changed=False)
        else:
            updated = dict(current, id=uid(), number=current["number"] + 1, parent=current["id"],
                           at=time.time(), prompt=job["prompt"], title=task["title"].strip())
            put("version", updated, db)
            put("meta", {"id": "current", "version": updated["id"]}, db)
            task.update(status="committed", version=updated["id"], changed=True)
        put("job", job, db)
    events(job["id"], "system", "Document title updated" if task["changed"] else "Document already has the requested title", task_id=task["id"])
    return True


def finish_job(job):
    statuses = [task["status"] for task in job["tasks"]]
    changes = sum(task["status"] == "committed" and task.get("changed", True) for task in job["tasks"])
    pending = sum(status in ("disputed", "evidence_required", "waiting", "blocked", "needs_input") for status in statuses)
    job["status"] = "needs_attention" if pending else "complete"
    job["summary"] = (f"{changes} document change(s) saved." if changes else "No document changes saved.")
    if pending:
        job["summary"] += f" {pending} task(s) need your attention."
    elif statuses and all(s == "inquiry" for s in statuses):
        job["summary"] = "Inquiry answered; document unchanged."
    put("job", job)


def validate_proposal(proposal, section, sources, check_evidence=True):
    """Syntactic and citation checks; model agreement never counts as verification."""
    if not isinstance(proposal, dict) or proposal.get("section_id") != section["id"]:
        return "Proposal targets a different section"
    if proposal.get("operation") not in ("append", "replace_block", "replace_section"):
        return "Unsupported operation"
    if proposal["operation"] == "replace_block" and proposal.get("block_id") not in {b["id"] for b in section["blocks"]}:
        return "Unknown block"
    if not isinstance(proposal.get("text"), str) or not proposal["text"].strip():
        return "Empty proposed text"
    claims = proposal.get("claims", [])
    if not isinstance(claims, list):
        return "Invalid claims"
    source_by_id = {s["id"]: s for s in sources}
    for claim in claims:
        if not isinstance(claim, dict) or not claim.get("text"):
            return "Invalid claim"
        cites = claim.get("citations", [])
        if not isinstance(cites, list) or any(not isinstance(cite, dict) for cite in cites):
            return "Invalid citations"
        if not check_evidence:
            continue
        if not cites:
            return "Evidence required for claim: " + str(claim["text"])[:100]
        for cite in cites:
            if not isinstance(cite, dict) or cite.get("source_id") not in source_by_id:
                return "Citation points to an unknown source"
            quote = cite.get("quote", "")
            if not isinstance(quote, str) or len(quote.strip()) < 12 or quote not in source_by_id[cite["source_id"]]["text"]:
                return "Citation quote was not found in the uploaded source"
    return None


def apply_proposal(version, proposal, prompt):
    next_version = copy.deepcopy(version)
    section = next(s for s in next_version["sections"] if s["id"] == proposal["section_id"])
    block = {"id": uid(), "type": "paragraph", "text": proposal["text"], "claims": proposal.get("claims", [])}
    if proposal["operation"] == "append":
        section["blocks"].append(block)
    elif proposal["operation"] == "replace_section":
        section["blocks"] = [block]
    else:
        old = next(b for b in section["blocks"] if b["id"] == proposal["block_id"])
        block["id"] = old["id"]
        section["blocks"][section["blocks"].index(old)] = block
    next_version.update(id=uid(), number=version["number"] + 1, parent=version["id"], at=time.time(), prompt=prompt)
    return next_version


def commit(task, job, allow_unverified=False):
    with LOCK, connect() as db:
        current = paper()
        section = next((s for s in current["sections"] if s["id"] == task["section_id"]), None)
        if section != task.get("base_section", section):
            task.update(status="blocked", reason="This section changed after review. Request a new revision against the latest draft.")
            put("job", job, db)
            return False
        if section is None:
            if not task.get("new_section"):
                task.update(status="blocked", reason="The target section no longer exists.")
                put("job", job, db)
                return False
            current = copy.deepcopy(current)
            section = {"id": task["section_id"], "heading": task["heading"], "blocks": []}
            anchor = next((s for s in current["sections"] if s["id"] == task.get("anchor_id")), None)
            if task.get("placement") and anchor is None:
                task.update(status="blocked", reason="The destination section no longer exists. Please request the edit again.")
                put("job", job, db)
                return False
            position = current["sections"].index(anchor) + (task["placement"] == "after") if anchor else len(current["sections"])
            current["sections"].insert(position, section)
        # Recheck the target against the latest version, including prior partial commits.
        issue = validate_proposal(task["proposal"], section, source_context(), check_evidence=not allow_unverified)
        if not issue and job.get("selection"):
            issue = validate_selection_proposal(task["proposal"], job["selection"], section)
        if issue:
            task["status"] = "evidence_required" if "Evidence" in issue or "Citation" in issue else "blocked"
            task["reason"] = issue
            put("job", job, db)
            db.commit()
            return False
        next_version = apply_proposal(current, task["proposal"], job["prompt"])
        if allow_unverified:
            override = {"at": time.time(), "job_id": job["id"], "task_id": task["id"],
                        "reason": task.get("reason", "Evidence check overridden by researcher")}
            task["evidence_override"] = override
            target = next(s for s in next_version["sections"] if s["id"] == task["section_id"])
            block = (next(b for b in target["blocks"] if b["id"] == task["proposal"]["block_id"])
                     if task["proposal"]["operation"] == "replace_block" else target["blocks"][-1])
            block["evidence_override"] = override
        put("version", next_version, db)
        put("meta", {"id": "current", "version": next_version["id"]}, db)
        task["status"] = "committed"
        task["version"] = next_version["id"]
        put("job", job, db)
        db.commit()
    events(job["id"], "researcher" if allow_unverified else "system",
           "Allowed revision without verified evidence" if allow_unverified else "Committed an uncontested revision",
           task_id=task["id"], version=next_version["number"])
    return True


def run_job(job_id, project_id=None):
    # Worker threads must capture their originating project, never the UI's selection.
    with project_scope(project_id or PROJECT.get()):
        token = RUN.set(job_id)
        try:
            _run_job(job_id)
        finally:
            RUN.reset(token)


def review_draft(task, job, current, section, selection, sources, feedback=None):
    job_id = job["id"]
    context = model_sources(sources, task["instruction"], job.get("source_ids", []))
    events(job_id, "writer", "Preparing section revision", task_id=task["id"])
    proposal = llm("writer", WRITING_POLICY + "Write a precise revision using supplied evidence for factual scientific claims. "
                   "Write Markdown (including lists, code and subheadings where appropriate). "
                   "Return {section_id,operation:'append'|'replace_block'|'replace_section',block_id:null|string,text,claims:[{text,citations:[{source_id,quote}]}],rationale}. "
                   "Use replace_section for a rewrite of the whole section; do not duplicate existing content. "
                   "For a selection, use replace_block and return the whole block with ONLY the selected substring changed; preserve its prefix and suffix exactly. "
                   "Each factual scientific assertion must be listed as a claim. Quotes must be exact source substrings. "
                   "Never invent results, references, methods or data. Editorial and prospective prose may have claims:[]. "
                   "If a specific factual/results request cannot be fulfilled, return {needs_input:string} asking for the missing data. "
                   "Do not insert apologies, unavailable-content notices, or editing status messages into the paper. "
                   "If review_feedback is supplied, revise to address every objection. Remove unsupported assertions; "
                   "do not disguise them as established findings. When no sources exist, a provisional abstract should "
                   "describe only the intended question, scope, and issues to examine, without background factual claims.",
                   {"instruction": task["instruction"], "user_request": job["prompt"], "recent_requests": request_context(),
                    "document": document_outline(current), "section": section, "selection": selection, "sources": context,
                    "selected_source_ids": job.get("source_ids", []), "review_feedback": feedback})
    if isinstance(proposal, dict) and isinstance(proposal.get("needs_input"), str) and proposal["needs_input"].strip():
        task.update(status="needs_input", reason=proposal["needs_input"])
        put("job", job)
        return
    task["proposal"] = proposal
    issue = validate_proposal(proposal, section, sources)
    if not issue and selection:
        issue = validate_selection_proposal(proposal, selection, section)
    if issue:
        task.update(status="evidence_required", reason=issue)
        events(job_id, "evidence", issue, task_id=task["id"])
        put("job", job)
        return
    role = "methodology" if "method" in section["heading"].lower() or "experiment" in task["instruction"].lower() else "skeptic"
    events(job_id, role, "Independently reviewing the proposal", task_id=task["id"])
    review = llm(role, WRITING_POLICY + "Independently scrutinize whether the proposed wording follows from the supplied evidence, "
                 "whether claims are missing from the claims list, and whether the change matches the instruction. "
                 "Return {objections:[string], rationale:string}. Treat an unsupported inference as an objection.",
                 {"instruction": task["instruction"], "document": document_outline(current), "section": section,
                  "text": proposal["text"], "claims": proposal.get("claims", []), "sources": context,
                  "selected_source_ids": job.get("source_ids", [])})
    task["review"] = review
    objections = review.get("objections")
    if not isinstance(objections, list):
        task.update(status="blocked", reason="Reviewer returned invalid assessment")
    elif objections:
        task.update(status="disputed", reason="; ".join(map(str, objections)))
        events(job_id, role, "Review objection raised", task_id=task["id"], detail=review)
    # Audit every revision, even if the writer omitted a claim from its list.
    audit = llm("evidence", WRITING_POLICY + "Audit every factual scientific assertion in the proposed text, including omissions from the claims list. "
                "Return {unsupported_claims:[string],objections:[string],rationale:string}. "
                "Put claims lacking sufficient uploaded evidence in unsupported_claims; put other interpretive disagreements in objections.",
                {"instruction": task["instruction"], "document": document_outline(current),
                 "text": proposal["text"], "claims": proposal.get("claims", []), "sources": context,
                 "selected_source_ids": job.get("source_ids", [])})
    task["audit"] = audit
    if not isinstance(audit.get("unsupported_claims"), list) or not isinstance(audit.get("objections"), list):
        task.update(status="blocked", reason="Evidence auditor returned invalid assessment")
    elif audit["unsupported_claims"]:
        task.update(status="evidence_required", reason="; ".join(map(str, audit["unsupported_claims"])))
        events(job_id, "evidence", "Additional evidence required", task_id=task["id"], detail=audit)
    elif audit["objections"]:
        task.update(status="disputed" if isinstance(objections, list) else "blocked",
                    reason="; ".join(map(str, (objections if isinstance(objections, list) else []) + audit["objections"])))
        events(job_id, "evidence", "Evidence interpretation disputed", task_id=task["id"], detail=audit)
    put("job", job)


def _run_job(job_id):
    job = get("job", job_id)
    if not job:
        return
    try:
        version = paper()
        job["status"] = "running"
        put("job", job)
        events(job_id, "planner", "Splitting the instruction into document tasks")
        selection = job.get("selection")
        if selection:
            validate_selection(selection, version)
        sources = source_context()
        selected_ids = validate_source_ids(job.get("source_ids", []), sources)
        selected_sources = [{"id": s["id"], "title": s["title"]} for s in sources if s["id"] in selected_ids]
        job["tasks"] = plan_tasks(job["prompt"], version, selection, selected_sources)
        put("job", job)
        sources = prioritize_sources(sources, selected_ids)
        for index, task in enumerate(job["tasks"]):
            if any(job["tasks"][d]["status"] != "committed" for d in task["depends_on"]):
                task.update(status="waiting", reason="Dependent task has not been committed")
                put("job", job)
                continue
            if task["operation"] == "clarify":
                task.update(status="needs_input", reason=task["instruction"])
                put("job", job)
                continue
            if task["operation"] == "set_title":
                commit_title(task, job)
                continue
            if task["operation"] == "move_section":
                commit_move(task, job)
                continue
            if not task["change_requested"]:
                task["status"] = "inquiry"
                task["finding"] = llm("skeptic", "Explore the research question, assumptions, alternatives, and uncertainties. Return {finding:string}.",
                                      {"instruction": task["instruction"], "document": paper(), "selection": selection,
                                       "selected_source_ids": selected_ids,
                                       "sources": model_sources(sources, task["instruction"], selected_ids)})
                events(job_id, "skeptic", "Inquiry finding ready", task_id=task["id"], detail=task["finding"])
                put("job", job)
                continue
            current = paper()
            section = next((s for s in current["sections"] if s["id"] == task["section_id"]), None)
            task["base_section"] = copy.deepcopy(section)
            if section is None:
                if not task["new_section"]:
                    raise ValueError("The target section no longer exists")
                section = {"id": task["section_id"], "heading": task["heading"], "blocks": []}
            if selection:
                validate_selection(selection, current)
            feedback = None
            for attempt in range(2):
                for field in ("reason", "proposal", "review", "audit"):
                    task.pop(field, None)
                task["status"] = "created"
                review_draft(task, job, current, section, selection, sources, feedback)
                snapshot = {key: copy.deepcopy(task[key]) for key in
                            ("proposal", "review", "audit", "status", "reason") if key in task}
                task.setdefault("attempts", []).append(snapshot)
                if task["status"] not in ("disputed", "evidence_required") or attempt == 1:
                    break
                feedback = snapshot
                events(job_id, "writer", "Revising draft to address review feedback", task_id=task["id"])
            if task["status"] == "created":
                commit(task, job)
            put("job", job)
        finish_job(job)
        events(job_id, "system", job["summary"])
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        put("job", job)
        events(job_id, "system", "Run stopped: " + str(exc))


def decide(job_id, task_id, choice):
    with LOCK:
        return _decide(job_id, task_id, choice)


def _decide(job_id, task_id, choice):
    job = get("job", job_id)
    if not job:
        raise ValueError("Unknown run")
    if job["status"] in ("queued", "running"):
        raise ValueError("Wait for this request to finish before deciding on its revision")
    task = next((t for t in job["tasks"] if t["id"] == task_id), None)
    if not task or task["status"] not in ("disputed", "evidence_required"):
        raise ValueError("Task is not awaiting a decision")
    if choice == "reject":
        task["status"] = "rejected"
        put("job", job)
        events(job_id, "researcher", "Rejected disputed revision", task_id=task_id)
    elif choice == "allow" and task["status"] == "evidence_required":
        if not commit(task, job, allow_unverified=True):
            raise ValueError(task["reason"])
    elif choice == "approve" and task["status"] == "disputed":
        # A researcher's choice cannot bypass source existence checks.
        if not commit(task, job):
            raise ValueError(task["reason"])
        events(job_id, "researcher", "Approved disputed revision", task_id=task_id)
    else:
        raise ValueError("Choose allow for evidence-required revisions, approve for disputed revisions, or reject")
    if job["status"] != "running":
        finish_job(job)
    return job


def undo():
    with LOCK, connect() as db:
        current = paper()
        if not current["parent"]:
            raise ValueError("No earlier version")
        parent = get("version", current["parent"])
        # Undo itself creates a new version; history stays immutable.
        restored = copy.deepcopy(parent)
        restored.update(id=uid(), number=current["number"] + 1, parent=current["id"], at=time.time(), prompt="Undo")
        put("version", restored, db)
        put("meta", {"id": "current", "version": restored["id"]}, db)
        db.commit()
    return restored


def markdown(version):
    parts = ["# " + version["title"]]
    for section in version["sections"]:
        if section["heading"]:
            parts.append("## " + section["heading"])
        parts.extend(block["text"] for block in section["blocks"])
    return "\n\n".join(parts) + "\n"


def save_markdown(text, base_version):
    if not isinstance(text, str) or not text.strip() or len(text) > 500000:
        raise ValueError("Provide Markdown of up to 500,000 characters")
    with LOCK, connect() as db:
        current = paper()
        if current["id"] != base_version:
            raise ValueError("The document changed. Copy your edits, then reopen the latest draft before saving.")
        title = current["title"]
        sections, lines, heading, fence = [], [], "", None

        def flush():
            body = "\n".join(lines).strip()
            if body or heading:
                # Preserve IDs and evidence metadata only when the content is unchanged.
                old = next((s for s in current["sections"] if s["heading"] == heading
                            and s["id"] not in {item["id"] for item in sections}), None)
                if old and body == "\n\n".join(b["text"] for b in old["blocks"]):
                    sections.append(copy.deepcopy(old))
                else:
                    sections.append({"id": old["id"] if old else uid(), "heading": heading,
                                     "blocks": [{"id": uid(), "type": "markdown", "text": body, "claims": []}] if body else []})

        for index, line in enumerate(text.strip().splitlines()):
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if marker:
                token = marker[1]
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence) and not line.strip()[len(token):].strip():
                    fence = None
                lines.append(line)
            elif fence is None and index == 0 and line.startswith("# "):
                title = line[2:].strip() or "Untitled document"
            elif fence is None and line.startswith("## "):
                flush()
                heading, lines = line[3:].strip(), []
            else:
                lines.append(line)
        flush()
        new = dict(current, id=uid(), number=current["number"] + 1, parent=current["id"],
                   at=time.time(), prompt="Edited Markdown", title=title, sections=sections)
        put("version", new, db)
        put("meta", {"id": "current", "version": new["id"]}, db)
        db.commit()
        return new


def validate_selection(selection, version):
    if not isinstance(selection, dict) or selection.get("version_id") != version["id"]:
        raise ValueError("The document changed. Select the passage again in the latest draft.")
    section = next((s for s in version["sections"] if s["id"] == selection.get("section_id")), None)
    block = next((b for b in section["blocks"] if b["id"] == selection.get("block_id")), None) if section else None
    start, end = selection.get("start"), selection.get("end")
    if (not block or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block["text"])
            or block["text"][start:end] != selection.get("text")):
        raise ValueError("Invalid selection. Select a passage from a single document block.")


def validate_selection_proposal(proposal, selection, section):
    if proposal.get("operation") != "replace_block" or proposal.get("block_id") != selection["block_id"]:
        return "Revision must only replace the selected passage"
    original = next(b["text"] for b in section["blocks"] if b["id"] == selection["block_id"])
    prefix, suffix = original[:selection["start"]], original[selection["end"]:]
    if (not proposal["text"].startswith(prefix) or not proposal["text"].endswith(suffix)
            or len(proposal["text"]) < len(prefix) + len(suffix)):
        return "Revision changed text outside the selected passage"
    return None


def latex(version):
    def esc(s):
        for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")]:
            s = s.replace(a, b)
        return s
    lines = [r"\documentclass{article}", r"\usepackage[utf8]{inputenc}", r"\title{" + esc(version["title"]) + "}",
             r"\begin{document}", r"\maketitle"]
    for s in version["sections"]:
        lines.append(r"\section{" + esc(s["heading"]) + "}")
        lines.extend(esc(b["text"]) + "\n" for b in s["blocks"])
    lines.append(r"\end{document}")
    return "\n".join(lines)
