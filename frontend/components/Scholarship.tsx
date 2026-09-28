import { useState } from 'react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs'
import { Action, Proposal, type Mutate } from './Activity'
import { Markdown } from './Markdown'
import { byTime, label, stamp } from '@/lib/api'
import type { Job, Snapshot } from '@/types'

export function Scholarship({
  state,
  mutate,
  inspect,
  openPanel,
}: {
  state: Snapshot
  mutate: Mutate
  inspect: (id: string, prefix?: string) => Promise<void>
  openPanel: (job: Job) => void
}) {
  const [tab, setTab] = useState('discussion')
  const { sessions, memory } = state.scholarship
  const sessionAction = (job: Job, action: string, text = '', extra = {}) =>
    mutate(`/api/sessions/${job.id}/${action}`, { text, ...extra })
  const contribute = (job: Job, action: string, reply_to?: string) => {
    const text = window.prompt(
      ['continue', 'redirect'].includes(action)
        ? 'What objective should the next round pursue?'
        : 'Your contribution or instruction',
    )
    if (text?.trim()) return sessionAction(job, action, text, { reply_to })
  }
  return (
    <Tabs value={tab} onValueChange={setTab} id="scholarshipPanel">
      <TabsList className="session-tabs" aria-label="Scholarship views">
        {['discussion', 'decisions', 'memory', 'activity'].map((value) => (
          <TabsTrigger key={value} value={value} data-tab={value}>
            {value[0].toUpperCase() + value.slice(1)}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value={tab} id="scholarshipContent" key={tab}>
        {tab === 'memory' ? (
          <>
            {[...memory].reverse().map((item) => (
              <div className="card" key={item.id}>
                <strong>
                  {label(item.kind)} · {item.status}
                </strong>
                <p>{item.text}</p>
                <p className="hint">
                  {item.authority} ·{' '}
                  {item.stale ? 'Document changed; recheck' : 'Recorded against current document'}
                </p>
                {item.turn_id && (
                  <Action
                    onAction={() => {
                      setTab('discussion')
                      requestAnimationFrame(() =>
                        document
                          .querySelector(`[data-turn-id="${CSS.escape(item.turn_id!)}"]`)
                          ?.scrollIntoView({ block: 'center' }),
                      )
                    }}
                  >
                    View originating discussion
                  </Action>
                )}
                {item.evidence_status && (
                  <p className="hint">Evidence: {label(item.evidence_status)}</p>
                )}
                {(item.citations || []).map((citation, i) => (
                  <Action
                    key={i}
                    onAction={() =>
                      inspect(citation.source_id, `${citation.quote}\n\nFull source:\n`)
                    }
                  >
                    Inspect quotation
                  </Action>
                ))}
                <Action
                  onAction={() => {
                    const text = window.prompt('Correct this memory entry', item.text)
                    if (text !== null)
                      return mutate('/api/memory', { id: item.id, action: 'correct', text })
                  }}
                >
                  Correct
                </Action>
                <Action
                  onAction={() =>
                    mutate('/api/memory', {
                      id: item.id,
                      action: item.status === 'resolved' ? 'reopen' : 'resolve',
                      text: '',
                    })
                  }
                >
                  {item.status === 'resolved' ? 'Reopen' : 'Resolve'}
                </Action>
                {!!item.history.length && (
                  <details>
                    <summary>Correction history</summary>
                    {item.history.map((entry, i) => (
                      <p key={i}>
                        {entry.action}: {entry.text}
                      </p>
                    ))}
                  </details>
                )}
              </div>
            ))}
            {!memory.length && (
              <p>Assumptions, alternatives, questions, and your decisions will appear here.</p>
            )}
          </>
        ) : (
          <>
            {byTime(sessions)
              .reverse()
              .map((job) => (
                <section className="activity-run" data-session-id={job.id} key={job.id}>
                  <div className="card">
                    <strong>{job.prompt}</strong>
                    <span className="stamp">{stamp(job.at)}</span>
                    <p>
                      {label(job.status)} · Round {job.round}
                    </p>
                    <p>{job.summary}</p>
                    <p className="hint">
                      {job.mode === 'revise'
                        ? `${job.tasks.filter((t) => ['committed', 'rejected', 'superseded'].includes(t.status)).length}/${job.tasks.length} editing tasks resolved`
                        : job.mode === 'review'
                          ? `${(job.coverage || []).length} sections reviewed`
                          : `${job.contributions}/6 contributions`}{' '}
                      · {job.calls}/40 provider attempts
                    </p>
                    {tab === 'discussion' && (
                      <>
                        {['queued', 'running'].includes(job.status) && (
                          <>
                            <Action onAction={() => sessionAction(job, 'pause')}>Pause</Action>
                            <Action onAction={() => sessionAction(job, 'hand')}>My turn</Action>
                            <Action onAction={() => sessionAction(job, 'stop')}>Stop</Action>
                          </>
                        )}
                        {job.status === 'paused' && (
                          <Action onAction={() => sessionAction(job, 'resume')}>Resume</Action>
                        )}
                        {job.status !== 'completed' && (
                          <>
                            <Action onAction={() => contribute(job, 'turn')}>Reply</Action>
                            <Action onAction={() => contribute(job, 'inject')}>
                              Inject context
                            </Action>
                          </>
                        )}
                        <Action onAction={() => contribute(job, 'redirect')}>Redirect</Action>
                        <Action onAction={() => contribute(job, 'continue')}>
                          {job.status === 'completed'
                            ? 'Start follow-up'
                            : job.mode === 'revise'
                              ? 'Continue request'
                              : 'Continue round'}
                        </Action>
                        {job.tasks.some((t) =>
                          [
                            'awaiting_approval',
                            'disputed',
                            'needs_input',
                            'waiting',
                            'blocked',
                          ].includes(t.status),
                        ) && (
                          <>
                            {job.tasks
                              .filter((t) =>
                                [
                                  'awaiting_approval',
                                  'disputed',
                                  'needs_input',
                                  'waiting',
                                  'blocked',
                                ].includes(t.status),
                              )
                              .map((task) => (
                                <p key={task.id}>
                                  {task.instruction}: {task.reason || label(task.status)}
                                </p>
                              ))}
                            <Action onAction={() => setTab('decisions')}>
                              View decisions / required input
                            </Action>
                          </>
                        )}
                        {job.status === 'paused' && (
                          <>
                            <Action onAction={() => openPanel(job)}>Edit panel</Action>
                            <Action onAction={() => sessionAction(job, 'recommend_panel')}>
                              Recommend panel
                            </Action>
                          </>
                        )}
                        {job.checkpoint &&
                          !['queued', 'running', 'completed'].includes(job.status) && (
                            <Action onAction={() => sessionAction(job, 'finalize')}>
                              Mark reviewed
                            </Action>
                          )}
                        <details>
                          <summary>Participants and model diversity</summary>
                          {job.panel.map((member, i) => (
                            <p key={member.id || i}>
                              {member.perspective} · {member.provider} /{' '}
                              {job.actual_models?.[member.id || ''] || member.model}
                            </p>
                          ))}
                          <p className="hint">
                            {new Set(
                              job.panel.map((member) =>
                                (job.actual_models?.[member.id || ''] || member.model).replace(
                                  /:free$/,
                                  '',
                                ),
                              ),
                            ).size < job.panel.length
                              ? 'Reduced model diversity: participants share a model.'
                              : 'Different models can still share biases and errors.'}
                          </p>
                        </details>
                      </>
                    )}
                  </div>
                  {tab === 'discussion' ? (
                    <>
                      {job.turns.map((turn) => (
                        <div className="card contribution" data-turn-id={turn.id} key={turn.id}>
                          <strong>
                            {turn.role}
                            {turn.ignored ? ' · repeated contribution' : ''}
                          </strong>
                          <span className="stamp">{stamp(turn.at)}</span>
                          <Markdown text={turn.text} />
                          {turn.model && (
                            <p className="hint">
                              {turn.model}
                              {turn.independent ? ' · independent initial assessment' : ''}
                            </p>
                          )}
                          {turn.reply_to && <p className="hint">In reply to {turn.reply_to}</p>}
                          <Action onAction={() => contribute(job, 'turn', turn.id)}>
                            Challenge / reply
                          </Action>
                        </div>
                      ))}
                      {job.checkpoint && (
                        <div className="card checkpoint">
                          <strong>Researcher checkpoint</strong>
                          <p>{job.checkpoint.summary || 'Review the discussion.'}</p>
                          {(['disagreements', 'missing_evidence', 'choices'] as const).map(
                            (key) =>
                              job.checkpoint?.[key] && (
                                <div key={key}>
                                  <strong>{label(key)}</strong>
                                  {job.checkpoint[key]?.map((text, i) => (
                                    <p key={i}>{text}</p>
                                  ))}
                                </div>
                              ),
                          )}
                        </div>
                      )}
                      {job.mode === 'review' && (
                        <p className="hint">
                          Reviewed sections: {(job.coverage || []).length}.{' '}
                          {job.review_version !== state.paper.id
                            ? 'Document changed; review is stale.'
                            : (job.coverage || []).length === state.paper.sections.length &&
                                job.synthesis_complete
                              ? 'All current sections covered, with cross-section synthesis.'
                              : 'Partial review: section coverage or cross-section synthesis remains unfinished.'}
                        </p>
                      )}
                    </>
                  ) : tab === 'decisions' ? (
                    job.tasks.map((task) => (
                      <Proposal
                        key={task.id}
                        job={job}
                        task={task}
                        mutate={mutate}
                        inspect={inspect}
                      />
                    ))
                  ) : (
                    [...job.activity]
                      .sort((a, b) => a.seq - b.seq)
                      .map((event) => (
                        <div className="card activity-event" key={event.id}>
                          <strong>
                            {event.seq} · {event.kind}
                          </strong>
                          <span className="stamp">{stamp(event.at)}</span>
                          <p>{event.message}</p>
                          <details>
                            <summary>Details</summary>
                            <pre>{JSON.stringify(event, null, 2)}</pre>
                          </details>
                        </div>
                      ))
                  )}
                </section>
              ))}
            {!sessions.length && (
              <p>
                Ask a research question, request a revision, or review your paper. Generated prose
                waits for Allow unless Allow all is checked.
              </p>
            )}
            {tab === 'activity' && state.jobs.some((job) => job.schema !== 2) && (
              <details>
                <summary>Legacy request history (read-only)</summary>
                {byTime(state.jobs.filter((job) => job.schema !== 2))
                  .reverse()
                  .map((job) => (
                    <p key={job.id}>
                      {job.prompt} · {job.status}
                    </p>
                  ))}
              </details>
            )}
          </>
        )}
      </TabsContent>
    </Tabs>
  )
}
