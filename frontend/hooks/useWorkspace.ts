import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Snapshot } from '@/types'

export function useWorkspace(project: string, fallback: () => void) {
  const [state, setState] = useState<Snapshot | null>(null)
  const [message, setMessage] = useState('')
  const current = useRef(project)
  current.current = project
  const pending = useRef<{
    project: string
    promise: Promise<void>
    controller: AbortController
  } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const notice = useCallback((error: unknown) => {
    clearTimeout(timer.current)
    setMessage(error instanceof Error ? error.message : String(error))
    timer.current = setTimeout(() => setMessage(''), 8500)
  }, [])
  const refresh = useCallback(() => {
    if (pending.current?.project === project) return pending.current.promise
    pending.current?.controller.abort()
    const controller = new AbortController()
    const promise = api<Snapshot>('/api/state', project, undefined, controller.signal)
      .then((next) => {
        if (current.current === project && !controller.signal.aborted) {
          // Retain state and node identity across unchanged polling snapshots.
          setState((previous) =>
            JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
          )
        }
      })
      .catch((error) => {
        if (current.current === project && !controller.signal.aborted) {
          notice(error)
          if (error.message === 'Unknown project') fallback()
        }
      })
      .finally(() => {
        if (pending.current?.controller === controller) pending.current = null
      })
    pending.current = { project, promise, controller }
    return promise
  }, [project, notice, fallback])
  useEffect(() => {
    setState(null)
    setMessage('')
    void refresh()
    const interval = setInterval(() => void refresh(), 1800)
    return () => {
      clearInterval(interval)
      pending.current?.controller.abort()
    }
  }, [refresh])
  useEffect(() => () => clearTimeout(timer.current), [])
  return { state: state?.project.id === project ? state : null, refresh, notice, message }
}
