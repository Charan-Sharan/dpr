import { useState, type ReactNode } from 'react'
import { Button } from './ui/button'
import { Markdown } from './Markdown'
import { byTime, label, stamp } from '@/lib/api'
import type { Activity, Job, Task } from '@/types'

export type Mutate = (path: string, body: unknown) => Promise<unknown>
export function Action({
  children,
  onAction,
  disabled = false,
}: {
  children: ReactNode
  onAction: () => unknown | Promise<unknown>
  disabled?: boolean
}) {
  const [pending, setPending] = useState(false)
  return (
    <Button
      size="sm"
      variant="secondary"
      disabled={disabled || pending}
      onClick={async () => {
        setPending(true)
        try {
          await onAction()
        } finally {
          setPending(false)
        }
      }}
    >
      {children}
    </Button>
  )
}
export function DecisionSection({
  title,
  text,
  kind,
  markdown = false,
}: {
  title: string
  text?: string
  kind: string
  markdown?: boolean
}) {
  return (
    <section className={`decision-section decision-${kind}`}>
      <h3 className="decision-label">{title}</h3>
      <div className="decision-body">{markdown ? <Markdown text={text || ''} /> : text}</div>
    </section>
  )
}
export function LegacyDecision({ job, task, mutate }: { job: Job; task: Task; mutate: Mutate }) {
  if (
    !['awaiting_approval', 'disputed', 'waiting', 'blocked', 'needs_input', 'inquiry'].includes(
      task.status,
    )
  )
    return null
  const reason = task.reason || task.finding?.finding
  return (
    <div className={`card ${task.status === 'disputed' ? 'warning' : ''}`}>
      <strong>
        {label(task.status).toUpperCase()} · {task.instruction}
      </strong>
      {reason && (
        <DecisionSection
          title={task.status === 'inquiry' ? 'Finding' : 'Review concerns'}
          text={reason}
          kind="review"
        />
      )}
      {task.proposal && (
        <>
          <DecisionSection title="Proposed text" text={task.proposal.text} kind="proposed" />
          {task.review && (
            <DecisionSection title="Review" text={task.review.rationale} kind="review" />
          )}
        </>
      )}
      {task.audit && (
        <DecisionSection
          title="Source review (optional)"
          text={task.audit.rationale}
          kind="audit"
        />
      )}
      {task.proposal && ['awaiting_approval', 'disputed'].includes(task.status) && (
        <div className="decision-actions">
          {['allow', 'reject'].map((choice) => (
            <Action
              key={choice}
              disabled={['queued', 'running'].includes(job.status)}
              onAction={() => mutate('/api/decide', { job_id: job.id, task_id: task.id, choice })}
            >
              {choice === 'allow' ? 'Allow' : 'Reject'}
            </Action>
          ))}
        </div>
      )}
    </div>
  )
}
export function LegacyActivity({
  jobs,
  events,
  mutate,
}: {
  jobs: Job[]
  events: Activity[]
  mutate: Mutate
}) {
  return (
    <>
      {byTime(jobs)
        .reverse()
        .map((job) => (
          <section className="activity-run" data-job-id={job.id} key={job.id}>
            <div className="card">
              <strong>Your request · {label(job.status)}</strong>
              <span className="stamp">{stamp(job.at)}</span>
              <p>{job.prompt}</p>
              {job.summary && <p>{job.summary}</p>}
            </div>
            {job.status === 'error' && (
              <div className="card error">
                <strong>Run failed</strong>
                <p>{job.error}</p>
              </div>
            )}
            {(job.tasks || []).map((task) => (
              <LegacyDecision key={task.id} job={job} task={task} mutate={mutate} />
            ))}
            {byTime(events.filter((event) => event.job_id === job.id)).map((event) => (
              <div className="card activity-event" data-event-id={event.id} key={event.id}>
                <strong>
                  {event.role} · {event.message}
                </strong>
                <span className="stamp">{stamp(event.at)}</span>
                {!!event.detail && <p>{JSON.stringify(event.detail)}</p>}
              </div>
            ))}
          </section>
        ))}
    </>
  )
}
export function Proposal({
  job,
  task,
  mutate,
  inspect,
}: {
  job: Job
  task: Task
  mutate: Mutate
  inspect: (source: string, prefix?: string) => Promise<void>
}) {
  async function decide(choice: string) {
    let rationale = ''
    if (choice === 'revise') {
      rationale = window.prompt('What should change in this revision?') || ''
      if (!rationale.trim()) return
    }
    await mutate(`/api/sessions/${job.id}/decide`, { task_id: task.id, choice, rationale })
  }
  const disabled = ['queued', 'running'].includes(job.status)
  return (
    <div className="card" data-task-id={task.id}>
      <strong>{task.instruction}</strong>
      <p>{label(task.status)}</p>
      {task.reason && (
        <DecisionSection
          title={task.status === 'committed' ? 'Original review concerns' : 'Review concerns'}
          text={task.reason}
          kind="review"
        />
      )}
      {task.proposal && (
        <>
          <details>
            <summary>Before</summary>
            <pre className="diff-before">{task.before || '(empty section)'}</pre>
          </details>
          <DecisionSection
            title={task.status === 'committed' ? 'Approved text' : 'Proposed text — not saved'}
            text={task.proposal.text}
            kind="proposed"
            markdown
          />
          {task.diff && (
            <details>
              <summary>Line-by-line diff</summary>
              <pre>{task.diff}</pre>
            </details>
          )}
          {task.review && (
            <DecisionSection title="Review" text={task.review.rationale} kind="review" />
          )}
          {task.audit && (
            <DecisionSection
              title="Source review (optional)"
              text={task.audit.rationale}
              kind="audit"
            />
          )}
          {(Array.isArray(task.proposal.claims) ? task.proposal.claims : []).flatMap((claim, i) =>
            (Array.isArray(claim?.citations) ? claim.citations : [])
              .filter((c) => c && typeof c.source_id === 'string')
              .map((citation, j) => (
                <Action
                  key={`${i}-${j}`}
                  disabled={disabled}
                  onAction={() =>
                    inspect(
                      citation.source_id,
                      `Claim: ${claim.text}\n\nQuoted passage: ${citation.quote}\n\nFull source:\n`,
                    )
                  }
                >
                  Inspect source passage
                </Action>
              )),
          )}
        </>
      )}
      {['awaiting_approval', 'disputed', 'blocked', 'needs_input'].includes(task.status) && (
        <div className="decision-actions">
          {['awaiting_approval', 'disputed'].includes(task.status) && (
            <Action disabled={disabled} onAction={() => decide('allow')}>
              Allow
            </Action>
          )}
          <Action disabled={disabled} onAction={() => decide('revise')}>
            Request revision
          </Action>
          <Action disabled={disabled} onAction={() => decide('reject')}>
            Reject
          </Action>
        </div>
      )}
    </div>
  )
}
