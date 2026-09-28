import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { useWorkspace } from './useWorkspace'
import type { Snapshot } from '@/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
const snapshot = (id: string) => ({ project: { id }, paper: { id: 'version-' + id } }) as Snapshot
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })

it('ignores delayed snapshots from a previous project and aborts its request', async () => {
  let finishOld!: (response: Response) => void
  let oldSignal: AbortSignal | undefined
  const fetch = vi.fn().mockImplementation((url: string, options: RequestInit) => {
    if (url.includes('project=old')) {
      oldSignal = options.signal as AbortSignal
      return new Promise<Response>((resolve) => {
        finishOld = resolve
      })
    }
    return Promise.resolve(response(snapshot('new')))
  })
  vi.stubGlobal('fetch', fetch)
  const fallback = vi.fn()
  const { result, rerender } = renderHook(({ project }) => useWorkspace(project, fallback), {
    initialProps: { project: 'old' },
  })
  rerender({ project: 'new' })
  await waitFor(() => expect(result.current.state?.project.id).toBe('new'))
  expect(oldSignal?.aborted).toBe(true)
  await act(async () => {
    finishOld(response(snapshot('old')))
  })
  expect(result.current.state?.project.id).toBe('new')
})

it('retains unchanged snapshot identity during polling', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(response(snapshot('default')))),
  )
  const fallback = vi.fn()
  const { result } = renderHook(() => useWorkspace('default', fallback))
  await waitFor(() => expect(result.current.state).not.toBeNull())
  const original = result.current.state
  await act(() => result.current.refresh())
  expect(result.current.state).toBe(original)
})

it('reports errors and recovers an unknown project to the default', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: 'Unknown project' }, 400)))
  const fallback = vi.fn()
  const { result } = renderHook(() => useWorkspace('missing', fallback))
  await waitFor(() => expect(fallback).toHaveBeenCalledOnce())
  expect(result.current.message).toBe('Unknown project')
  expect(result.current.state).toBeNull()
})
