export async function api<T = unknown>(
  path: string,
  project: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(
    `${path}${path.includes('?') ? '&' : '?'}project=${encodeURIComponent(project)}`,
    {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    },
  )
  const data = await response.json()
  if (!response.ok) throw Error(data.error || 'Request failed')
  return data
}
export const byTime = <T extends { at: number }>(items: T[]) =>
  [...items].sort((a, b) => (a.at || 0) - (b.at || 0))
export const stamp = (at: number) => (at ? new Date(at * 1000).toLocaleString() : '')
export const label = (value: string) => value.replaceAll('_', ' ')
