import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { FileText, Plus, Undo2, Download, ArrowUpRight, RotateCcw } from 'lucide-react'
import { Button } from './components/ui/button'
import { Textarea } from './components/ui/input'
import { Document } from './components/Document'
import { LegacyActivity } from './components/Activity'
import { Scholarship } from './components/Scholarship'
import { Forms, type Modal } from './components/Forms'
import { useWorkspace } from './hooks/useWorkspace'
import { api } from './lib/api'
import { markdownSelection } from './lib/selection'
import type { Selection, Snapshot, Source } from './types'

export function App() {
  const [project, setProject] = useState(
    () => new URLSearchParams(location.search).get('project') || 'default',
  )
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const modeRef = useRef<HTMLSelectElement>(null)
  const drafts = useRef(new Map<string, string>())
  const references = useRef(new Map<string, Map<string, string>>())
  const [busy, setBusy] = useState(false)
  const [approvalPreferences, setApprovalPreferences] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem('dpr-allow-all') || '{}')
    } catch {
      return {}
    }
  })
  const allowAll = approvalPreferences[project] === true
  const busyRef = useRef(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const selectionRef = useRef(selection)
  selectionRef.current = selection
  const [modal, setModal] = useState<Modal | null>(null)
  const [wide, setWide] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(false)
  const switchProject = useCallback(
    (id: string) => {
      if (busyRef.current) return
      if (promptRef.current) {
        drafts.current.set(project, promptRef.current.value)
        promptRef.current.value = drafts.current.get(id) || ''
      }
      setSelection(null)
      setModal(null)
      setProject(id)
      history.replaceState(null, '', '?project=' + encodeURIComponent(id))
    },
    [project],
  )
  const fallback = useCallback(() => switchProject('default'), [switchProject])
  const { state, refresh, notice, message } = useWorkspace(project, fallback)
  const stateRef = useRef<Snapshot | null>(state)
  stateRef.current = state
  const activeProject = useRef(project)
  activeProject.current = project
  const capture = useCallback(() => {
    const selected = window.getSelection(),
      current = stateRef.current
    if (!selected?.rangeCount || selected.isCollapsed || !current) return
    const range = selected.getRangeAt(0)
    const blockOf = (node: Node) =>
      (node.nodeType === Node.ELEMENT_NODE
        ? (node as Element)
        : node.parentElement
      )?.closest<HTMLElement>('.markdown-block')
    const startBlock = blockOf(range.startContainer),
      endBlock = blockOf(range.endContainer)
    if (!startBlock || startBlock !== endBlock) {
      setSelection(null)
      notice(
        'Select text within one document block. For a broader change, describe the section in your request.',
      )
      return
    }
    const section = current.paper.sections.find(
      (section) => section.id === startBlock.dataset.sectionId,
    )
    const block = section?.blocks.find((block) => block.id === startBlock.dataset.blockId)
    if (!section || !block) return
    const passage = markdownSelection(startBlock, range, block.text)
    if (!passage) {
      setSelection(null)
      notice(
        'Could not locate that passage in the draft. Select the text again or describe the passage in your request.',
      )
      return
    }
    setSelection({
      version_id: current.paper.id,
      section_id: section.id,
      block_id: block.id,
      ...passage,
    })
  }, [notice])
  useLayoutEffect(() => {
    if (selectionRef.current && state && selectionRef.current.version_id !== state.paper.id) {
      setSelection(null)
      notice('The document changed. Select the passage again to revise it.')
    }
  }, [state?.paper.id, notice, state])
  useEffect(() => {
    document.body.classList.toggle('discussion-wide', wide)
    return () => document.body.classList.remove('discussion-wide')
  }, [wide])
  async function mutate(path: string, body: unknown) {
    try {
      const result = await api(path, project, body)
      if (activeProject.current === project) await refresh()
      return result
    } catch (error) {
      if (activeProject.current === project) notice(error)
    }
  }
  async function inspect(id: string, prefix = '') {
    try {
      const source = await api<Source>('/api/source/' + id, project)
      if (activeProject.current === project)
        setModal({ kind: 'detail', text: `${source.title}\n\n${prefix}${source.text}` })
    } catch (error) {
      if (activeProject.current === project) notice(error)
    }
  }
  function addReference(source: Source) {
    const prompt = promptRef.current!
    const marker = `Source: “${source.title}”`
    if (!references.current.has(project)) references.current.set(project, new Map())
    references.current.get(project)!.set(source.id, marker)
    if (!prompt.value.includes(marker)) {
      const before = prompt.value.slice(0, prompt.selectionStart),
        after = prompt.value.slice(prompt.selectionEnd)
      prompt.setRangeText(
        (before && !/\s$/.test(before) ? ' ' : '') +
          marker +
          (after && !/^\s/.test(after) ? ' ' : ' '),
        prompt.selectionStart,
        prompt.selectionEnd,
        'end',
      )
    }
    prompt.focus()
  }
  async function run() {
    const prompt = promptRef.current?.value.trim()
    if (
      !prompt ||
      busyRef.current ||
      !state ||
      state.jobs.some((job) => ['queued', 'running'].includes(job.status))
    )
      return
    busyRef.current = true
    setBusy(true)
    try {
      await api('/api/run', project, {
        prompt,
        allow_all: allowAll,
        selection,
        source_ids: [...(references.current.get(project) || new Map<string, string>())]
          .filter(([, marker]) => prompt.includes(marker))
          .map(([id]) => id),
        mode: modeRef.current?.value || 'auto',
      })
      promptRef.current!.value = ''
      references.current.delete(project)
      setSelection(null)
      await refresh()
    } catch (error) {
      notice(error)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }
  const enabled = !!state?.project.dpr_enabled
  const active = state?.jobs.some((job) => ['queued', 'running'].includes(job.status))
  const exportQuery = '?project=' + encodeURIComponent(project)
  return (
    <>
      <header>
        <div className="brand">
          <span className="mark">D</span>
          <div>
            <strong>DPR Workspace</strong>
            <small>Inquiry · scrutiny · documentation</small>
          </div>
        </div>
        <div className="toolbar">
          <span id="version">{state ? 'Version ' + state.paper.number : 'Loading…'}</span>
          <Button
            id="undo"
            variant="secondary"
            size="sm"
            disabled={!state?.paper.parent || busy}
            onClick={() => void mutate('/api/undo', {})}
          >
            <Undo2 />
            Undo
          </Button>
          <Button asChild variant="ghost" size="sm">
            <a id="exportMarkdown" href={'/api/markdown' + exportQuery} download="document.md">
              <Download />
              Export Markdown
            </a>
          </Button>
        </div>
      </header>
      <div className="project-bar">
        <div>
          <label htmlFor="projectSelect">Project</label>
          <select
            id="projectSelect"
            value={project}
            disabled={busy}
            onChange={(event) => switchProject(event.target.value)}
            aria-label="Current project"
          >
            {state ? (
              state.projects.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.name}
                </option>
              ))
            ) : (
              <option value={project}>Loading…</option>
            )}
          </select>
          <Button
            id="newProject"
            variant="secondary"
            size="sm"
            disabled={busy || !state}
            onClick={() => setModal({ kind: 'project' })}
          >
            <Plus />
            New project
          </Button>
        </div>
        <span id="providerStatus" role="status">
          {state
            ? state.providers
                .map(
                  (provider) =>
                    (provider.id === 'groq' ? 'Groq' : 'OpenRouter') +
                    ': ' +
                    (provider.configured ? 'key configured' : 'key missing'),
                )
                .join(' · ')
            : 'Checking provider configuration…'}
        </span>
        <label className="scholarship-switch">
          <input
            id="scholarshipEnabled"
            type="checkbox"
            checked={enabled}
            disabled={!state || busy}
            onChange={(event) => void mutate('/api/scholarship', { enabled: event.target.checked })}
          />{' '}
          Enable DPR scholarship
        </label>
      </div>
      <main>
        <aside className={`outline ${outlineOpen ? 'mobile-open' : ''}`}>
          <h2>Paper outline</h2>
          <nav id="outline">
            {state?.paper.sections
              .filter((section) => section.heading)
              .map((section) => (
                <a href={'#' + section.id} key={section.id}>
                  {section.heading}
                </a>
              ))}
          </nav>
          <hr />
          <h2>Evidence</h2>
          <div id="sources">
            {state?.sources.map((source) => (
              <div className="source-item" key={source.id}>
                <Button
                  variant="ghost"
                  className="source-open"
                  title={'View ' + source.title}
                  onClick={() => void inspect(source.id)}
                >
                  <FileText />
                  <span>{source.title}</span>
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="source-reference"
                  aria-label={'Add ' + source.title + ' to prompt'}
                  onClick={() => addReference(source)}
                >
                  Add reference
                </Button>
              </div>
            ))}
          </div>
          <Button
            id="addSource"
            variant="secondary"
            disabled={!state}
            onClick={() => setModal({ kind: 'source' })}
          >
            <Plus />
            Add source
          </Button>
          <p className="hint">
            Sources are stored locally. Relevant excerpts are sent to configured AI providers when
            you make a request.
          </p>
          <p className="hint">
            Scholarship is opt-in: discussion, reasoning memory, and approval before generated prose
            is saved.
          </p>
        </aside>
        <section className="center">
          <Button
            className="mobile-outline"
            variant="secondary"
            size="sm"
            aria-expanded={outlineOpen}
            onClick={() => setOutlineOpen(!outlineOpen)}
          >
            {outlineOpen ? 'Hide' : 'Show'} outline & sources
          </Button>
          <div className="paper-scroll">
            <div className="paper-head">
              <span id="documentStatus">
                {state
                  ? 'LATEST SAVED DOCUMENT · ' +
                    new Date(state.paper.at * 1000).toLocaleTimeString()
                  : 'LOADING PROJECT'}
              </span>
              <div>
                <Button
                  variant="ghost"
                  size="sm"
                  id="editMarkdown"
                  disabled={!state}
                  onClick={() => state && setModal({ kind: 'markdown', paper: state.paper })}
                >
                  Edit Markdown
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  id="editTitle"
                  disabled={!state}
                  onClick={() => {
                    const title = window.prompt('Paper title', state?.paper.title)
                    if (title?.trim()) void mutate('/api/title', { title })
                  }}
                >
                  Edit title
                </Button>
              </div>
            </div>
            {state ? (
              <Document
                key={project}
                paper={state.paper}
                sources={state.sources}
                capture={capture}
              />
            ) : (
              <article id="paper" aria-busy="true">
                <p className="empty-state">Loading your document…</p>
              </article>
            )}
          </div>
          <div className="composer">
            <label className="request-mode" hidden={!enabled}>
              Mode{' '}
              <select id="requestMode" ref={modeRef} defaultValue="auto">
                <option value="auto">Auto</option>
                <option value="discuss">Discuss</option>
                <option value="revise">Revise</option>
                <option value="review">Review whole paper</option>
              </select>
            </label>
            <div id="selectionContext" hidden={!selection}>
              <span id="selectionText">{selection ? `Selected: “${selection.text}”` : ''}</span>
              <Button
                id="clearSelection"
                variant="secondary"
                size="sm"
                onClick={() => setSelection(null)}
              >
                Clear selection
              </Button>
            </div>
            <label htmlFor="prompt">Ask a question or describe a revision</label>
            <Textarea
              id="prompt"
              ref={promptRef}
              rows={3}
              placeholder="Ask a research question, describe a revision, or select a passage to rephrase…"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault()
                  void run()
                }
              }}
            />
            <div className="compose-foot">
              <span>
                {allowAll
                  ? 'Valid proposed text saves automatically.'
                  : 'Proposed text waits for your Allow decision.'}
              </span>
              <Button id="run" disabled={!state || active || busy} onClick={() => void run()}>
                {active ? (
                  'Reviewing your request…'
                ) : busy ? (
                  'Sending…'
                ) : (
                  <>
                    Send request <ArrowUpRight />
                  </>
                )}
              </Button>
            </div>
          </div>
        </section>
        <aside className="activity">
          <div className="panel-title">
            <h2 id="activityTitle">{enabled ? 'Inquiry workspace' : 'Agent activity'}</h2>
            <Button
              id="expandDiscussion"
              variant="secondary"
              size="sm"
              hidden={!enabled}
              aria-expanded={wide}
              onClick={() => setWide(!wide)}
            >
              {wide ? 'Collapse' : 'Expand'}
            </Button>
            <span className="live">● Live</span>
          </div>
          <label
            className="approval-preference"
            style={{ display: 'flex', gap: 8, padding: '12px 16px', alignItems: 'center' }}
          >
            <input
              id="allowAll"
              type="checkbox"
              checked={allowAll}
              onChange={(event) => {
                const next = { ...approvalPreferences, [project]: event.target.checked }
                setApprovalPreferences(next)
                try {
                  localStorage.setItem('dpr-allow-all', JSON.stringify(next))
                } catch {
                  /* Keep the preference for this visit. */
                }
              }}
            />
            <span>
              Allow all <small> · applies to new requests</small>
            </span>
          </label>
          <div id="notice" role="status">
            {message}
          </div>
          {enabled && state && (
            <>
              <Scholarship
                key={project}
                state={state}
                mutate={mutate}
                inspect={inspect}
                openPanel={(job) => setModal({ kind: 'panel', job })}
              />
              <a
                id="exportAudit"
                href={'/api/audit' + exportQuery}
                download="scholarship-audit.json"
              >
                Export reasoning audit
              </a>
            </>
          )}
          <div id="events" hidden={enabled}>
            {state && !enabled && (
              <LegacyActivity
                jobs={state.jobs.filter((job) => job.schema !== 2)}
                events={state.events}
                mutate={mutate}
              />
            )}
          </div>
          <hr />
          <h2>Versions</h2>
          <div id="versions">
            {state &&
              [...state.versions]
                .sort((a, b) => b.number - a.number)
                .slice(0, 20)
                .map((version) => {
                  const current = version.id === state.paper.id
                  return (
                    <div className="version-row" key={version.id}>
                      <Button
                        variant="ghost"
                        className="version-item"
                        onClick={async () => {
                          try {
                            const item = await api<Snapshot['paper']>(
                              '/api/version/' + version.id,
                              project,
                            )
                            if (activeProject.current === project)
                              setModal({
                                kind: 'detail',
                                text:
                                  'Version ' +
                                  item.number +
                                  '\n' +
                                  item.title +
                                  '\n\n' +
                                  item.sections
                                    .map(
                                      (section) =>
                                        section.heading +
                                        '\n' +
                                        section.blocks.map((block) => block.text).join('\n'),
                                    )
                                    .join('\n\n'),
                              })
                          } catch (error) {
                            if (activeProject.current === project) notice(error)
                          }
                        }}
                      >
                        v{version.number} · {version.prompt}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="version-restore"
                        disabled={current || busy}
                        title={
                          current
                            ? 'This is the current version'
                            : `Restore version ${version.number}`
                        }
                        aria-label={
                          current
                            ? `Version ${version.number} is current`
                            : `Restore version ${version.number}`
                        }
                        onClick={() => {
                          if (
                            window.confirm(
                              `Restore version ${version.number}? This creates a new version and keeps the full history.`,
                            )
                          )
                            void mutate('/api/restore', { version_id: version.id })
                        }}
                      >
                        <RotateCcw />
                        Restore
                      </Button>
                    </div>
                  )
                })}
          </div>
        </aside>
      </main>
      {modal && (
        <Forms
          key={project + modal.kind}
          modal={modal}
          project={project}
          close={() => setModal(null)}
          refresh={refresh}
          switchProject={switchProject}
        />
      )}
    </>
  )
}
