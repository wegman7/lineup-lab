// Minimal Server-Sent Events parser. The browser's EventSource only does GET, and /chat is a
// POST, so the stream is read with fetch() and parsed here. Frames can be split across chunks:
// whatever follows the last blank line is returned as `buffer` for the next call.

export interface RawEvent {
  event: string
  data: unknown
}

export function parseSSE(chunk: string, buffer: string): { events: RawEvent[]; buffer: string } {
  const text = (buffer + chunk).replace(/\r\n/g, '\n')
  const frames = text.split('\n\n')
  const rest = frames.pop() ?? ''
  const events: RawEvent[] = []
  for (const frame of frames) {
    let event = 'message'
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length) events.push({ event, data: JSON.parse(data.join('\n')) })
  }
  return { events, buffer: rest }
}
