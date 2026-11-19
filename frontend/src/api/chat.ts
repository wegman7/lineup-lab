import { parseSSE } from './sse'
import type { Meta, ServerEvent } from './types'

export async function fetchMeta(): Promise<Meta> {
  const r = await fetch('/api/meta')
  if (!r.ok) throw new Error(`meta: ${r.status}`)
  return r.json()
}

/** POST a question and call onEvent for each SSE frame. Abort `signal` to stop (Stop button). */
export async function streamChat(
  question: string,
  chatId: string | null,
  signal: AbortSignal,
  onEvent: (e: ServerEvent) => void,
): Promise<{ chatId: string | null }> {
  const r = await fetch('/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question, chat_id: chatId }),
    signal,
  })
  if (!r.ok || !r.body) {
    let message = 'Something went wrong. Please try again.'
    try {
      const body = await r.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      /* not JSON */
    }
    onEvent({ event: 'error', data: { message } })
    return { chatId }
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    const parsed = parseSSE(value, buffer)
    buffer = parsed.buffer
    for (const e of parsed.events) onEvent(e as ServerEvent)
  }
  return { chatId: r.headers.get('x-chat-id') }
}
