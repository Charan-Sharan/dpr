import { useRef, useState, type FormEvent } from 'react'
import { Button } from './ui/button'
import { Input, Textarea } from './ui/input'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog'
import { api } from '@/lib/api'
import type { Job, Paper, Participant, Project } from '@/types'

export type Modal =
  | { kind: 'source' | 'project' }
  | { kind: 'markdown'; paper: Paper }
  | { kind: 'detail'; text: string }
  | { kind: 'panel'; job: Job }
export function titleFromFilename(filename: string) {
  return filename
    .replace(/\.(pdf|txt|md)$/i, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 200)
}
export function documentMarkdown(paper: Paper) {
  return (
    [
      '# ' + paper.title,
      ...paper.sections.flatMap((section) => [
        ...(section.heading ? ['## ' + section.heading] : []),
        ...section.blocks.map((block) => block.text),
      ]),
    ].join('\n\n') + '\n'
  )
}
function value(form: HTMLFormElement, name: string) {
  return (form.elements.namedItem(name) as HTMLInputElement).value
}
const defaultParticipant = (): Participant => ({
  perspective: 'Additional perspective',
  provider: 'groq',
  model: 'openai/gpt-oss-20b',
  role: 'skeptic',
})

export function Forms({
  modal,
  project,
  close,
  refresh,
  switchProject,
}: {
  modal: Modal
  project: string
  close: () => void
  refresh: () => Promise<void>
  switchProject: (id: string) => void
}) {
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [suggested, setSuggested] = useState(false)
  const titleEdited = useRef(false)
  const titleRef = useRef<HTMLInputElement>(null)
  const [members, setMembers] = useState(() =>
    modal.kind === 'panel' ? modal.job.panel.map((member, i) => ({ ...member, rowId: i })) : [],
  )
  const nextRow = useRef(members.length)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    const form = event.currentTarget
    setPending(true)
    setError('')
    try {
      if (modal.kind === 'project') {
        const created = await api<Project>('/api/projects', project, {
          name: value(form, 'projectName'),
        })
        close()
        switchProject(created.id)
        return
      }
      if (modal.kind === 'markdown')
        await api('/api/markdown', project, {
          markdown: value(form, 'markdownEditor'),
          base_version: modal.paper.id,
        })
      if (modal.kind === 'source') {
        const file = (form.elements.namedItem('sourceFile') as HTMLInputElement).files?.[0]
        const title = value(form, 'sourceTitle').trim()
        if (file?.name.toLowerCase().endsWith('.pdf')) {
          const base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve(String(reader.result).split(',')[1])
            reader.onerror = () => reject(Error('Could not read the PDF'))
            reader.readAsDataURL(file)
          })
          await api('/api/evidence/pdf', project, { title, base64 })
        } else
          await api('/api/evidence', project, {
            title,
            text: value(form, 'sourceText') || (await file?.text()),
          })
      }
      if (modal.kind === 'panel') {
        const panel = Array.from(form.querySelectorAll('#panelRows > fieldset')).map((row) =>
          Object.fromEntries(
            Array.from(
              row.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input,select'),
            ).map((input) => [input.name, input.value]),
          ),
        )
        await api(`/api/sessions/${modal.job.id}/panel`, project, { panel })
      }
      close()
      await refresh()
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error))
    } finally {
      setPending(false)
    }
  }
  const title =
    modal.kind === 'source'
      ? 'Add research material'
      : modal.kind === 'project'
        ? 'New project'
        : modal.kind === 'markdown'
          ? 'Edit your document'
          : modal.kind === 'panel'
            ? 'Participant panel'
            : 'Source or document version'
  const description =
    modal.kind === 'source'
      ? 'Choose a text/PDF file or paste its contents. PDF extraction requires pdftotext.'
      : modal.kind === 'project'
        ? 'Start with a blank document and a separate set of sources and revisions.'
        : modal.kind === 'markdown'
          ? 'Use # for the title and ## for sections. Saving creates a version; direct edits bypass agent review.'
          : modal.kind === 'panel'
            ? 'Different perspectives do not guarantee independent reasoning. Configure model IDs available to your accounts.'
            : 'Read the saved content below.'
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) close()
      }}
    >
      <DialogContent
        id={`${modal.kind === 'detail' ? 'version' : modal.kind}Dialog`}
        className={modal.kind === 'markdown' ? 'max-w-4xl' : ''}
        onEscapeKeyDown={(event) => {
          if (pending) event.preventDefault()
        }}
        onPointerDownOutside={(event) => {
          if (pending) event.preventDefault()
        }}
      >
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        {modal.kind === 'detail' ? (
          <>
            <div id="versionDetail">{modal.text}</div>
            <Button id="closeVersion" onClick={close}>
              Close
            </Button>
          </>
        ) : (
          <form
            id={`${modal.kind}Form`}
            onSubmit={submit}
            onReset={() => {
              titleEdited.current = false
              setSuggested(false)
            }}
          >
            <fieldset disabled={pending} className="form-fields">
              {modal.kind === 'source' && (
                <>
                  <label htmlFor="sourceTitle">Source title</label>
                  <Input
                    ref={titleRef}
                    id="sourceTitle"
                    name="sourceTitle"
                    maxLength={200}
                    required
                    aria-describedby="sourceTitleHint"
                    onInput={(event) => {
                      titleEdited.current = !!event.currentTarget.value.trim()
                    }}
                  />
                  <p id="sourceTitleHint" className="hint" role="status">
                    {suggested
                      ? 'Suggested from the filename. You can edit it before saving.'
                      : 'Selecting a file suggests a title instantly, without an AI call.'}
                  </p>
                  <label htmlFor="sourceFile">Text or PDF file</label>
                  <Input
                    id="sourceFile"
                    name="sourceFile"
                    type="file"
                    accept=".txt,.md,.pdf,text/plain,application/pdf"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0]
                      if (
                        file &&
                        titleRef.current &&
                        (!titleEdited.current || !titleRef.current.value.trim())
                      ) {
                        titleRef.current.value = titleFromFilename(file.name)
                        setSuggested(true)
                      }
                    }}
                  />
                  <label htmlFor="sourceText">Or paste source text</label>
                  <Textarea
                    id="sourceText"
                    name="sourceText"
                    rows={10}
                    placeholder="Paste source text here…"
                  />
                </>
              )}
              {modal.kind === 'project' && (
                <>
                  <label htmlFor="projectName">Project name</label>
                  <Input
                    id="projectName"
                    name="projectName"
                    maxLength={120}
                    required
                    placeholder="Research paper or documentation"
                  />
                </>
              )}
              {modal.kind === 'markdown' && (
                <Textarea
                  id="markdownEditor"
                  name="markdownEditor"
                  rows={20}
                  aria-label="Document Markdown"
                  spellCheck={false}
                  defaultValue={documentMarkdown(modal.paper)}
                />
              )}
              {modal.kind === 'panel' && (
                <>
                  <div id="panelRows">
                    {members.map((member) => (
                      <fieldset key={member.rowId}>
                        {(['perspective', 'provider', 'model', 'role'] as const).map((field) => (
                          <label key={field}>
                            {field}
                            {['provider', 'role'].includes(field) ? (
                              <select name={field} defaultValue={member[field]} required>
                                {(field === 'provider'
                                  ? ['groq', 'openrouter']
                                  : ['writer', 'skeptic', 'methodology', 'evidence', 'planner']
                                ).map((option) => (
                                  <option key={option}>{option}</option>
                                ))}
                              </select>
                            ) : (
                              <Input name={field} defaultValue={member[field]} required />
                            )}
                          </label>
                        ))}
                        <Button
                          variant="secondary"
                          onClick={() =>
                            setMembers((previous) =>
                              previous.filter((row) => row.rowId !== member.rowId),
                            )
                          }
                        >
                          Remove
                        </Button>
                      </fieldset>
                    ))}
                  </div>
                  <Button
                    id="addParticipant"
                    variant="secondary"
                    disabled={members.length >= 5}
                    onClick={() =>
                      setMembers((previous) => [
                        ...previous,
                        { ...defaultParticipant(), rowId: nextRow.current++ },
                      ])
                    }
                  >
                    Add participant
                  </Button>
                </>
              )}
            </fieldset>
            <p
              id={modal.kind === 'markdown' ? 'editorError' : `${modal.kind}Error`}
              role="alert"
              className="form-error"
            >
              {error}
            </p>
            <div className="dialog-actions">
              <Button
                variant="secondary"
                id={`cancel${modal.kind[0].toUpperCase() + modal.kind.slice(1)}`}
                disabled={pending}
                onClick={close}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                id={
                  modal.kind === 'markdown'
                    ? 'saveMarkdown'
                    : modal.kind === 'project'
                      ? 'createProject'
                      : undefined
                }
                disabled={pending}
              >
                {pending
                  ? 'Saving…'
                  : modal.kind === 'source'
                    ? 'Save source'
                    : modal.kind === 'project'
                      ? 'Create project'
                      : modal.kind === 'markdown'
                        ? 'Save document'
                        : 'Save panel'}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
