import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Forms } from './Forms'
import { api } from '@/lib/api'
import type { Job, Paper } from '@/types'

vi.mock('@/lib/api', () => ({ api: vi.fn() }))
afterEach(() => {
  cleanup()
  vi.mocked(api).mockReset()
})
const callbacks = () => ({
  project: 'origin',
  close: vi.fn(),
  refresh: vi.fn().mockResolvedValue(undefined),
  switchProject: vi.fn(),
})

it('suggests filenames, preserves a custom title, resets, and uploads text to the originating project', async () => {
  vi.mocked(api).mockResolvedValue({})
  const props = callbacks()
  render(<Forms modal={{ kind: 'source' }} {...props} />)
  const title = screen.getByLabelText('Source title') as HTMLInputElement
  const file = screen.getByLabelText('Text or PDF file')
  fireEvent.change(file, { target: { files: [new File(['text'], '研究_Notes.txt')] } })
  expect(title.value).toBe('研究 Notes')
  fireEvent.input(title, { target: { value: 'Custom title' } })
  fireEvent.change(file, { target: { files: [new File(['text'], 'Replacement.pdf')] } })
  expect(title.value).toBe('Custom title')
  fireEvent.reset(document.querySelector('form')!)
  fireEvent.change(file, { target: { files: [new File(['text'], 'a'.repeat(220) + '.txt')] } })
  expect(title.value.length).toBe(200)
  fireEvent.change(screen.getByLabelText('Or paste source text'), {
    target: { value: 'Source contents' },
  })
  fireEvent.submit(document.querySelector('form')!)
  await waitFor(() => expect(props.close).toHaveBeenCalledOnce())
  expect(api).toHaveBeenCalledWith('/api/evidence', 'origin', {
    title: 'a'.repeat(200),
    text: 'Source contents',
  })
})

it('uploads PDFs as base64 and surfaces upload failures without closing', async () => {
  vi.mocked(api).mockRejectedValue(Error('PDF text extraction failed'))
  const props = callbacks()
  render(<Forms modal={{ kind: 'source' }} {...props} />)
  fireEvent.change(screen.getByLabelText('Text or PDF file'), {
    target: { files: [new File(['PDF data'], 'Study.pdf', { type: 'application/pdf' })] },
  })
  fireEvent.submit(document.querySelector('form')!)
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toBe('PDF text extraction failed'),
  )
  expect(api).toHaveBeenCalledWith('/api/evidence/pdf', 'origin', {
    title: 'Study',
    base64: btoa('PDF data'),
  })
  expect(props.close).not.toHaveBeenCalled()
})

it('keeps the editor open on stale saves and sends the version captured at opening', async () => {
  vi.mocked(api).mockRejectedValue(Error('The document changed. Reopen the editor.'))
  const props = callbacks()
  render(
    <Forms
      modal={{
        kind: 'markdown',
        paper: { id: 'base', title: 'Paper', sections: [] } as unknown as Paper,
      }}
      {...props}
    />,
  )
  fireEvent.change(screen.getByLabelText('Document Markdown'), { target: { value: '# Edited' } })
  fireEvent.submit(document.querySelector('form')!)
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('document changed'))
  expect(api).toHaveBeenCalledWith('/api/markdown', 'origin', {
    markdown: '# Edited',
    base_version: 'base',
  })
  expect(props.close).not.toHaveBeenCalled()
})

it('preserves edited participant fields when removing and adding rows', async () => {
  vi.mocked(api).mockResolvedValue({})
  const props = callbacks()
  render(
    <Forms
      modal={{
        kind: 'panel',
        job: {
          id: 'session',
          panel: [
            { perspective: 'First', provider: 'groq', model: 'a', role: 'writer' },
            { perspective: 'Second', provider: 'openrouter', model: 'b', role: 'skeptic' },
          ],
        } as Job,
      }}
      {...props}
    />,
  )
  const models = screen.getAllByLabelText('model')
  fireEvent.change(models[1], { target: { value: 'edited-model' } })
  fireEvent.click(screen.getAllByText('Remove')[0])
  fireEvent.click(screen.getByText('Add participant'))
  expect((screen.getAllByLabelText('model')[0] as HTMLInputElement).value).toBe('edited-model')
  fireEvent.submit(document.querySelector('form')!)
  await waitFor(() => expect(props.close).toHaveBeenCalledOnce())
  expect(api).toHaveBeenCalledWith('/api/sessions/session/panel', 'origin', {
    panel: [
      { perspective: 'Second', provider: 'openrouter', model: 'edited-model', role: 'skeptic' },
      {
        perspective: 'Additional perspective',
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        role: 'skeptic',
      },
    ],
  })
})
