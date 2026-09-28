import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LegacyActivity, Proposal } from './Activity'
import { Markdown } from './Markdown'
import type { Activity, Job, Task } from '@/types'

afterEach(cleanup)
describe('research workspace rendering', () => {
  it('groups decisions and chronological events under newest-first requests', () => {
    const jobs = [
      { id: 'new', at: 200, status: 'complete', prompt: 'New request', tasks: [] },
      {
        id: 'old',
        at: 100,
        status: 'needs_attention',
        prompt: 'Old request',
        tasks: [
          {
            id: 'old-task',
            status: 'disputed',
            instruction: 'Review claim',
            proposal: { text: 'Unverified claim' },
          },
        ],
      },
    ] as Job[]
    const events = [
      { id: 'finish', job_id: 'new', at: 203 },
      { id: 'old-review', job_id: 'old', at: 300 },
      { id: 'start', job_id: 'new', at: 201 },
    ] as Activity[]
    const mutate = vi.fn().mockResolvedValue(undefined)
    const { container, rerender } = render(
      <LegacyActivity jobs={jobs} events={events} mutate={mutate} />,
    )
    expect([...container.children].map((node) => (node as HTMLElement).dataset.jobId)).toEqual([
      'new',
      'old',
    ])
    expect(
      [...container.firstElementChild!.querySelectorAll('[data-event-id]')].map(
        (node) => (node as HTMLElement).dataset.eventId,
      ),
    ).toEqual(['start', 'finish'])
    expect(
      container.lastElementChild!.querySelector('[data-event-id]')?.getAttribute('data-event-id'),
    ).toBe('old-review')
    expect(container.firstElementChild!.querySelector('button')).toBeNull()
    expect(screen.getByText('Allow')).toBeTruthy()
    const text = container.textContent
    rerender(
      <LegacyActivity jobs={[...jobs].reverse()} events={[...events].reverse()} mutate={mutate} />,
    )
    expect(container.textContent).toBe(text)
  })
  it('escapes HTML and blocks script/data links and images', () => {
    const { container } = render(
      <Markdown
        text={
          '<img src=x onerror=alert(1)>\n\n[bad](javascript:alert) [data](data:text/html,test) [good](https://example.com)\n\n![image](https://example.com/image.png)'
        }
      />,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelectorAll('a[href]').length).toBe(1)
    expect(container.querySelector('a[href]')?.getAttribute('href')).toBe('https://example.com')
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })
  it('approves source-free prose normally and keeps optional source concerns informational', async () => {
    const mutate = vi.fn().mockResolvedValue(undefined)
    const task = {
      id: 'task',
      status: 'awaiting_approval',
      instruction: 'Revise',
      proposal: { text: '**Prose**', claims: [{ text: 'A claim', citations: [] }] },
      review: { rationale: 'Review text' },
      audit: { rationale: 'Source support is unavailable' },
    } as Task
    const { container, rerender } = render(
      <Proposal
        job={{ id: 'job', status: 'awaiting_approval' } as Job}
        task={task}
        mutate={mutate}
        inspect={vi.fn()}
      />,
    )
    expect(
      [...container.querySelectorAll('.decision-label')].map((node) => node.textContent),
    ).toEqual(['Proposed text — not saved', 'Review', 'Source review (optional)'])
    expect(screen.queryByText('Allow without verified evidence')).toBeNull()
    fireEvent.click(screen.getByText('Allow'))
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith('/api/sessions/job/decide', {
        task_id: 'task',
        choice: 'allow',
        rationale: '',
      }),
    )
    rerender(
      <Proposal
        job={{ id: 'job', status: 'running' } as Job}
        task={task}
        mutate={mutate}
        inspect={vi.fn()}
      />,
    )
    expect((screen.getByText('Reject') as HTMLButtonElement).disabled).toBe(true)
  })
})
