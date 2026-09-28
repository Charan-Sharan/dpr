# DPR Research Workspace · Markdown documents

A local, single-researcher workspace with multiple projects for human-directed, multi-agent paper revisions. It supports both GroqCloud and OpenRouter. Each project has an independent document, sources, requests, activity, and version history.

## DPR scholarship workflow (opt-in)

Restart `python3 server.py`, then select **Enable DPR scholarship** in the project bar. This is a per-project opt-in; existing projects keep the legacy workflow until enabled. The first startup of this version backs up an existing SQLite database before recording schema version 2. Existing documents and histories are retained. Interrupted jobs are marked for explicit continuation, never silently restarted.

Use **Discuss** for bounded multi-agent inquiry, **Revise** for proposed document edits, **Review whole paper** for coverage-tracked review, or **Auto** to classify the instruction. Generated prose—including rephrasing—does not enter the paper until you approve it in **Decisions**. Explicit title changes and section moves remain immediate and undoable. If the model invents a title instead of using the exact title you requested, you will be asked to specify it.

The right panel has **Discussion**, **Decisions**, **Memory**, and **Activity** tabs. Expand it for longer conversations. Pause to edit/recommend the participant panel. You can reply to a turn, inject context, redirect, stop, or request your own turn. Each inquiry round allows up to six contribution turns, three per participant, and 40 total provider attempts (including retries and fallback). Checkpoints preserve disagreements and ask for your next objective. Replies at the limit are saved without silently starting more model calls; use **Continue round** to authorize another bounded round.

Proposals include before/after text, a line diff, participant reviews, and optional source passage inspection. Sources and citations are optional. When sources are uploaded, the source review is advisory: its warnings or failures do not block saving or approval. Approval is conservative: any saved-document change requires refreshing pending proposals before approval. Approved prerequisites can resume waiting tasks within the remaining call budget.

Reasoning memory records assumptions, alternatives, claims, actions, open questions, and researcher decisions with provenance and correction history. Quotation matches are explicitly not semantic verification. Old memory is marked stale after the document changes. Whole-paper reviews process every section in bounded chunks, checkpoint their coverage, and synthesize findings in batches; partial reviews never appear complete. **Mark reviewed** applies only to the reviewed document version and is not a correctness certification.

Files are stored locally, but relevant source excerpts, paper context, and reasoning are sent to configured Groq/OpenRouter providers during model requests. No live calls happen during migration or recovery. Tests use mocked providers. This is a local prototype; live-provider quality and researcher learning benefits have not been evaluated. The legacy behavior below applies when the opt-in is disabled.

The reasoning workflow is an independent adaptation of [Multi-Agent-Reasoning](https://github.com/Skanda-P-R/Multi-Agent-Reasoning/tree/3bf193915b3a557637b7c8e6867e1c9a369bbd0e), not an imported engine or an API-compatible fork. `scholarship.py` handles durable sessions, participant scheduling, memory, and approval; `core.py` handles document validation and versioned commits; `providers.py` handles model requests; `server.py` serves the project-scoped API and static UI. Run one server process per database, on loopback only.

## Start

Python 3.10+; no Python packages required. Frontend development/builds require Node.js 22.12+ and npm. PDF extraction additionally needs `pdftotext` (Poppler).

```bash
git clone https://github.com/Charan-Sharan/dpr.git
cd dpr
cp .env.example .env
```

Copy `.env.example` to `.env`, replace the placeholder API keys, then start the server. `GROQ_API_KEY` and `OPEN_ROUTER_API_KEY` are supported; `OPENROUTER_API_KEY` is also accepted. Either provider can be used alone. `your_actual_key_here` is only a placeholder and will be rejected. `.env` is loaded automatically at startup, and existing process environment variables take precedence. Restart the server after configuration changes. Never paste keys into the web page or commit them. `.env`, local databases, and virtual environments are excluded from Git.

```bash
npm ci
npm run build
python3 server.py
```

Open `http://127.0.0.1:8765`. Start with **Edit Markdown** to paste or write a draft, or describe the document you want in the request box. Optionally add text/PDF sources for context. Data and versions are stored locally in `workspace.sqlite3`. Set `DPR_DB` for a different database path.

## Frontend development

The frontend uses React, TypeScript, Vite, Tailwind CSS, and locally owned shadcn/ui components. It keeps the document, evidence, and inquiry panes, with a mobile outline/source toggle. Python continues to serve the same project-scoped APIs and the built files in `static/`; no Node process or CDN is needed at runtime. Rebuild after changing frontend source. The generated `static/` assets are included with the project so it can still run with `python3 server.py` alone.

Run `python3 server.py` in one terminal and `npm run dev` in another. Open the Vite URL (normally `http://127.0.0.1:5173`); `/api` requests proxy to the Python server on port 8765. Run `npm run build` for TypeScript checks and production assets, `npm test` for component tests, and the Python/browser suite below for integrated workflows. Browser tests run against the production build.

UI primitives in `frontend/components/ui/` are adapted from [shadcn/ui](https://github.com/shadcn-ui/ui) under its MIT license (see `frontend/components/ui/LICENSE`). `components.json` configures the shadcn CLI and aliases; add further components with `npx shadcn@latest add <component>`. Workspace state and interaction logic belong in the app, not the reusable UI primitives.

## Projects

Use **+ New project** in the top bar, enter a name, and create a blank document. Use the adjacent project dropdown to switch. The selected project is encoded in the URL so refreshing/bookmarking retains it. Requests continue in their originating project when you switch. The old single-document workspace appears as **My first project**; its records and history are retained in place, without a destructive migration.

All document endpoints take `?project=<id>` (default: `default`). This scopes evidence uploads, runs, decisions, version lookup, Markdown saves/exports, title edits, and undo. `GET /api/projects` lists projects; `POST /api/projects` with `{"name":"My project"}` creates one. This is local data separation, not multi-user authentication.

## Providers and troubleshooting

The writer receives a concise document outline and bounded source excerpts to stay within provider token limits. Uploaded sources remain intact locally. Sources are optional context; their absence does not block a revision. For source-informed edits, name the topic or passage so the relevant excerpt can be selected.

With `DPR_PROVIDER=auto` (the default), planning/writing/evidence prefer Groq; skeptical/methodology review prefers OpenRouter. If the preferred provider fails or is not configured, the other configured provider is used. Transient failures receive one bounded retry. A failed writer or reviewer call does not bypass normal review. Optional source-review failures are recorded without blocking the revision. Activity logs show the actual provider/model attempts, and errors distinguish authentication, permissions, missing models, billing, rate limits, and invalid JSON. Keys are redacted.

| Role | Groq model | OpenRouter model |
| --- | --- | --- |
| Planner | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Writer | `openai/gpt-oss-120b` | `openai/gpt-oss-120b` |
| Skeptic | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Evidence | `openai/gpt-oss-20b` | `meta-llama/llama-3.3-70b-instruct` |
| Methodology | `openai/gpt-oss-20b` | `openai/gpt-oss-20b` |

Set `DPR_PROVIDER=groq` or `openrouter` to change the preferred provider globally, or `DPR_PROVIDER_WRITER` (and the other uppercase role names) per role. Override model IDs with `DPR_GROQ_MODEL_PLANNER`, `DPR_OPENROUTER_MODEL_WRITER`, etc. Legacy `DPR_MODEL_*` settings remain Groq-only. The UI's “key configured” indicator checks presence, not authentication or credits.

Run `python3 check_providers.py` to send a tiny JSON completion to each configured provider. `--models` lists available Groq models and relevant OpenRouter models. `--workflow` additionally runs a small live writing job in a temporary database without changing your documents. Live checks use provider quota/credits and never print keys.

## Writing workflow

The central view renders the latest saved document. It updates after a committed agent revision, a manual save, or undo. Proposed revisions, objections, and inquiry findings appear alongside the document; they are not presented as accepted prose. New workspaces start empty. Existing documents and version history are preserved.

- Ask “Update the introduction to explain…” or “Add an implementation section with these steps…”. Agents can append content, replace a block, rewrite a section, or create a section.
- Ask “Move Literature Survey after Introduction” to reorder an existing section directly. The move preserves its text, IDs, citations, and history, and creates an undoable version without calling a writing model. Minor heading typos are matched only when the destination is unambiguous. New sections requested “after Introduction” are inserted there rather than appended to the end.
- Click **Add reference** beside an uploaded source to insert its name at the cursor in the prompt. You can keep typing around it or add several sources. The request also carries the selected source IDs, so files with the same name remain distinct and selected files are prioritized in agent context. Removing the mention before sending removes its selection from that request.
- “Let's work on a paper titled …” sets the actual document title as a versioned edit, without creating a title section or requiring evidence checks. This changes the paper title, not the project name in the dropdown. Follow-ups can refer to recent requests in the same project.
- “Fill the abstract” can draft a provisional abstract from the title/topic, expressing scope and intended inquiry without inventing findings. Sources and citations are optional; normal review still checks clarity, consistency, and the requested change. If actual measurements or other essential information are missing, the app asks for that input alongside the document instead of inserting an unavailable-content message into the paper.
- Select a unique passage within one rendered block and ask “Rephrase the selected text”. The request includes the passage and its document version. Edits outside its surrounding boundaries are blocked. Selections crossing Markdown formatting or containing ambiguous repeated text currently require a more specific passage or a request describing the section.
- Use **Edit Markdown** to write directly. `#` on the first line sets the title; `##` starts a section. Lower headings stay within the section. Saving creates a version. Direct edits are human-authored and do not run agent evidence checks; changed blocks lose their prior evidence annotations.
- Use **Export Markdown** to download the current draft. LaTeX is deferred from the writing interface; the legacy export endpoint remains for compatibility.
- Ask questions or challenge an argument without requesting edits. Inquiry receives the current document and leaves it unchanged.

The local Markdown renderer supports headings, simple emphasis, links, fenced code, flat lists, blockquotes, and tables. Raw HTML is rendered as text and unsafe link schemes are disabled. It is a lightweight subset, not a complete CommonMark/GFM implementation: nested lists, images, footnotes, math, and complex nested inline formatting are not supported yet.

Request summaries distinguish saved changes from inquiry-only responses and tasks needing attention. Earlier request errors and findings remain with their requests below newer activity, so an old provider failure is not confused with the latest request. Source review is informational and separate from the decision to save a revision.

Agent activity is grouped by request, with newest requests first and each request's steps shown chronologically from top to bottom. Entries include dates and times. Updating an older request (for example, allowing a revision) keeps it in its original position, with the new event inside that request.

Normal review objections are sent back to the writer for one revision attempt, followed by fresh review. Both attempts are retained in the task history. Unresolved review objections still require human attention. Source-review warnings do not trigger a retry or a separate approval gate. To reproduce the title-then-abstract flow using live providers in a temporary database, run `python3 check_providers.py --writing-intent`.

The **Allow all** checkbox at the top of the right panel controls new requests and remembers its setting per project. It defaults to unchecked: generated proposals wait for **Allow** or **Reject** (scholarship also offers **Request revision**). When checked, structurally valid proposals save automatically, including proposals with review disagreements. Explicit title changes and section moves still save immediately. Source support is optional and is never an approval requirement. Existing proposals formerly held for source checks are presented for a normal decision and are never automatically saved during an upgrade. Historical records are retained, but documents no longer display the old evidence-override warning. Stale-edit, operation, and selection-boundary checks remain enforced.

## What works

- Versioned document with stable section/block IDs, Markdown rendering, manual draft editing, and Markdown export.
- Uploaded text and PDF evidence, with exact quoted passage checks.
- Groq/OpenRouter-backed planner, writer, skeptical/methodological reviewer, and optional source reviewer. The planner picks task scopes; methodology review is selected when relevant.
- Live event polling with proposals, objections, decisions, and inquiry findings.
- Independent tasks can commit separately. Disputed edits require a human decision; unsupported claims are blocked. Inquiry-only tasks leave the paper alone.
- Durable jobs, decisions, evidence, document snapshots, and undo as a new version.
- Polling preserves document nodes and selections until the saved version changes. Stale editor saves and proposals reviewed against an outdated section are blocked.

## DPR principles

The scholar directs the inquiry and owns the conclusions. The shared document is the persistent artifact of that inquiry. Reviewers challenge claims and interpretations; agreement among models is not proof. Uploaded sources support traceable evidence checks. Generated prose waits for explicit Allow in both workflows unless the researcher checks Allow all for new requests. Changes can be undone. Diverse perspectives can strengthen scrutiny, but models may share errors and role labels do not guarantee independent reasoning.

## Current limits

This is a local prototype, not a production scholarly verification system. Optional quote diagnostics check passage existence; source review is advisory and does not certify correctness. Failures of all configured providers can stop a run midway, leaving already committed independent tasks intact. A paused job can be inspected but not resumed automatically. The parser supports text-based PDFs, not scanned PDFs or tables as structured data. There is no account/authentication, journal template, citation formatter, rich equation editor, or web research. Run on the loopback interface only. Project rename/delete are not implemented.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests mock model output and require no API key. They cover citations, partial commits, disputes, undo, Markdown round trips, new sections, inquiry context, selection boundaries, stale-edit protection, provider fallback/retries/redaction/configuration, legacy project preservation, and background job isolation. If Chromium is installed, a browser test also checks rendering, safe Markdown, selection survival during polling, a selected-text revision through the API, manual saving, export, and project creation/switching/isolation. That test uses a temporary database and local server; it skips when Chromium is unavailable. Live checks are separate and opt-in through `check_providers.py`.
