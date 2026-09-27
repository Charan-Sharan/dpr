# DPR Research Workspace · Markdown documents

A local, single-researcher workspace with multiple projects for human-directed, multi-agent paper revisions. It supports both GroqCloud and OpenRouter. Each project has an independent document, sources, requests, activity, and version history.

## Start

Python 3.10+; no Python packages required. PDF extraction additionally needs `pdftotext` (Poppler).

```bash
cd dpr-workspace
python3 server.py
```

Put real keys in the local `.env` file using `.env.example` as a reference, then start the server. `GROQ_API_KEY` and `OPEN_ROUTER_API_KEY` are supported; `OPENROUTER_API_KEY` is also accepted. Either provider can be used alone. `your_actual_key_here` is only a placeholder and will be rejected. `.env` is loaded automatically at startup, and existing process environment variables take precedence. Restart the server after configuration changes. Never paste keys into the web page or commit them.

Open `http://127.0.0.1:8765`. Start with **Edit Markdown** to paste or write a draft, or describe the document you want in the request box. Add text/PDF sources to support scientific claims. Data and versions are stored locally in `workspace.sqlite3`. Set `DPR_DB` for a different database path.

## Projects

Use **+ New project** in the top bar, enter a name, and create a blank document. Use the adjacent project dropdown to switch. The selected project is encoded in the URL so refreshing/bookmarking retains it. Requests continue in their originating project when you switch. The old single-document workspace appears as **My first project**; its records and history are retained in place, without a destructive migration.

All document endpoints take `?project=<id>` (default: `default`). This scopes evidence uploads, runs, decisions, version lookup, Markdown saves/exports, title edits, and undo. `GET /api/projects` lists projects; `POST /api/projects` with `{"name":"My project"}` creates one. This is local data separation, not multi-user authentication.

## Providers and troubleshooting

The writer receives a concise document outline and bounded source excerpts to stay within provider token limits. Uploaded sources remain intact locally, and quote validation checks their full text. For evidence-backed edits, name the topic or passage so the relevant excerpt can be selected.

With `DPR_PROVIDER=auto` (the default), planning/writing/evidence prefer Groq; skeptical/methodology review prefers OpenRouter. If the preferred provider fails or is not configured, the other configured provider is used. Transient failures receive one bounded retry. A failed call does not bypass review or evidence validation. Activity logs show the actual provider/model attempts, and errors distinguish authentication, permissions, missing models, billing, rate limits, and invalid JSON. Keys are redacted.

| Role | Groq model | OpenRouter model |
| --- | --- | --- |
| Planner | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Writer | `openai/gpt-oss-120b` | `openai/gpt-oss-120b` |
| Skeptic | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Evidence | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Methodology | `openai/gpt-oss-20b` | `openai/gpt-oss-20b` |

Set `DPR_PROVIDER=groq` or `openrouter` to change the preferred provider globally, or `DPR_PROVIDER_WRITER` (and the other uppercase role names) per role. Override model IDs with `DPR_GROQ_MODEL_PLANNER`, `DPR_OPENROUTER_MODEL_WRITER`, etc. Legacy `DPR_MODEL_*` settings remain Groq-only. The UI's “key configured” indicator checks presence, not authentication or credits.

The previous Groq planner/evidence default, `llama-3.3-70b-versatile`, was unavailable in the authenticated model list during diagnosis and returned HTTP 404. The old implementation also hid all provider details behind a generic HTTP error and did not load `.env`. Earlier stored 403 errors cannot be diagnosed more precisely retrospectively. Provider error formats follow the [Groq error documentation](https://console.groq.com/docs/errors) and OpenRouter's [structured-output API](https://openrouter.ai/docs/guides/features/structured-outputs).

Run `python3 check_providers.py` to send a tiny JSON completion to each configured provider. `--models` lists available Groq models and relevant OpenRouter models. `--workflow` additionally runs a small live writing job in a temporary database without changing your documents. Live checks use provider quota/credits and never print keys.

## Writing workflow

The central view renders the latest saved document. It updates after a committed agent revision, a manual save, or undo. Proposed revisions, objections, and inquiry findings appear alongside the document; they are not presented as accepted prose. New workspaces start empty. Existing documents and version history are preserved.

- Ask “Update the introduction to explain…” or “Add an implementation section with these steps…”. Agents can append content, replace a block, rewrite a section, or create a section.
- Ask “Move Literature Survey after Introduction” to reorder an existing section directly. The move preserves its text, IDs, citations, and history, and creates an undoable version without calling a writing model. Minor heading typos are matched only when the destination is unambiguous. New sections requested “after Introduction” are inserted there rather than appended to the end.
- Click **Add reference** beside an uploaded source to insert its name at the cursor in the prompt. You can keep typing around it or add several sources. The request also carries the selected source IDs, so files with the same name remain distinct and selected files are prioritized in agent context. Removing the mention before sending removes its selection from that request.
- “Let's work on a paper titled …” sets the actual document title as a versioned edit, without creating a title section or requiring evidence checks. This changes the paper title, not the project name in the dropdown. Follow-ups can refer to recent requests in the same project.
- “Fill the abstract” can draft a provisional abstract from the title/topic, expressing scope and intended inquiry without inventing findings. Empirical assertions still require evidence. If actual measurements or other essential information are missing, the app asks for that input alongside the document instead of inserting an unavailable-content message into the paper.
- Select a unique passage within one rendered block and ask “Rephrase the selected text”. The request includes the passage and its document version. Edits outside its surrounding boundaries are blocked. Selections crossing Markdown formatting or containing ambiguous repeated text currently require a more specific passage or a request describing the section.
- Use **Edit Markdown** to write directly. `#` on the first line sets the title; `##` starts a section. Lower headings stay within the section. Saving creates a version. Direct edits are human-authored and do not run agent evidence checks; changed blocks lose their prior evidence annotations.
- Use **Export Markdown** to download the current draft. LaTeX is deferred from the writing interface; the legacy export endpoint remains for compatibility.
- Ask questions or challenge an argument without requesting edits. Inquiry receives the current document and leaves it unchanged.

The local Markdown renderer supports headings, simple emphasis, links, fenced code, flat lists, blockquotes, and tables. Raw HTML is rendered as text and unsafe link schemes are disabled. It is a lightweight subset, not a complete CommonMark/GFM implementation: nested lists, images, footnotes, math, and complex nested inline formatting are not supported yet.

Request summaries distinguish saved changes from inquiry-only responses and tasks needing attention. Earlier request errors and findings are grouped under expandable history so an old provider failure is not confused with the latest request. Editing rationales are not treated as scholarly assertions by the evidence auditor.

Agent activity is grouped by request, with newest requests first and each request's steps shown chronologically from top to bottom. Entries include dates and times. Updating an older request (for example, allowing a revision) keeps it in its original position, with the new event inside that request.

Review objections are sent back to the writer for one revision attempt, followed by fresh review and evidence checks. Both attempts are retained in the task history. Unresolved objections still require human attention; unsupported claims are never automatically approved. To reproduce the title-then-abstract flow using live providers in a temporary database, run `python3 check_providers.py --writing-intent`.

**Evidence required** means the proposed text did not pass its supporting-source checks. Once the request finishes, **Allow** saves that proposal by your explicit choice, without requiring verified evidence; **Reject** discards it. Allowed text is labeled “Allowed by you · evidence not verified”, with the original reason and decision retained in the task and document version. This does not turn the claim into a verified claim. Undo remains available. Allow does not bypass stale-edit, operation, or selection-boundary checks.

## What works

- Versioned document with stable section/block IDs, Markdown rendering, manual draft editing, and Markdown export.
- Uploaded text and PDF evidence, with exact quoted passage checks.
- Groq/OpenRouter-backed planner, writer, skeptical/methodological reviewer, and evidence auditor. The planner picks task scopes; methodology review is selected when relevant.
- Live event polling with proposals, objections, decisions, and inquiry findings.
- Independent tasks can commit separately. Disputed edits require a human decision; unsupported claims are blocked. Inquiry-only tasks leave the paper alone.
- Durable jobs, decisions, evidence, document snapshots, and undo as a new version.
- Polling preserves document nodes and selections until the saved version changes. Stale editor saves and proposals reviewed against an outdated section are blocked.

## DPR principles

The scholar directs the inquiry and owns the conclusions. The shared document is the persistent artifact of that inquiry. Reviewers challenge claims and interpretations; agreement among models is not proof. Uploaded sources support traceable evidence checks. Uncontested, reviewed changes requested by the human are committed automatically and can be undone; disputed proposals require a human decision. Diverse perspectives can strengthen scrutiny, but models may share errors and role labels do not guarantee independent reasoning.

## Current limits

This is a local prototype, not a production scholarly verification system. Exact quote validation checks passage existence; semantic support relies on the evidence auditor and must still be checked by the researcher. Failures of all configured providers can stop a run midway, leaving already committed independent tasks intact. A paused job can be inspected but not resumed automatically. The parser supports text-based PDFs, not scanned PDFs or tables as structured data. There is no account/authentication, journal template, citation formatter, rich equation editor, or web research. Run on the loopback interface only. Project rename/delete are not implemented.

## Tests

```bash
cd dpr-workspace
python3 -m unittest discover -s tests -v
```

Tests mock model output and require no API key. They cover citations, partial commits, disputes, undo, Markdown round trips, new sections, inquiry context, selection boundaries, stale-edit protection, provider fallback/retries/redaction/configuration, legacy project preservation, and background job isolation. If Chromium is installed, a browser test also checks rendering, safe Markdown, selection survival during polling, a selected-text revision through the API, manual saving, export, and project creation/switching/isolation. That test uses a temporary database and local server; it skips when Chromium is unavailable. Live checks are separate and opt-in through `check_providers.py`.
