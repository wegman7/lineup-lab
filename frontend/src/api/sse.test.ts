import { describe, expect, it } from 'vitest'
import { parseSSE } from './sse'

describe('parseSSE', () => {
  it('parses one frame', () => {
    const { events, buffer } = parseSSE('event: token\ndata: {"text":"hi"}\n\n', '')
    expect(events).toEqual([{ event: 'token', data: { text: 'hi' } }])
    expect(buffer).toBe('')
  })

  it('parses two frames in one chunk', () => {
    const chunk = 'event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {"total_ms":5}\n\n'
    const { events } = parseSSE(chunk, '')
    expect(events.map((e) => e.event)).toEqual(['token', 'done'])
  })

  it('keeps a frame split across chunks until it completes', () => {
    const first = parseSSE('event: token\ndata: {"te', '')
    expect(first.events).toEqual([])
    const second = parseSSE('xt":"hi"}\n\n', first.buffer)
    expect(second.events).toEqual([{ event: 'token', data: { text: 'hi' } }])
  })

  it('ignores comment lines', () => {
    const { events } = parseSSE(': keep-alive\n\nevent: token\ndata: {"text":"x"}\n\n', '')
    expect(events).toEqual([{ event: 'token', data: { text: 'x' } }])
  })

  it('handles CRLF line endings', () => {
    const { events } = parseSSE('event: token\r\ndata: {"text":"x"}\r\n\r\n', '')
    expect(events).toEqual([{ event: 'token', data: { text: 'x' } }])
  })
})
