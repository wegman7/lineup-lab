import { describe, expect, it } from 'vitest'
import { chatReducer, initialChat } from './chatReducer'
import type { StepEvent } from './api/types'

const step = (status: StepEvent['status'], summary = ''): StepEvent => ({
  id: 'sql-1', kind: 'sql', status, summary, detail: {}, duration_ms: null,
})

function started() {
  return chatReducer(initialChat, { type: 'ask', question: 'Puka targets?' })
}

describe('chatReducer', () => {
  it('ask adds a running exchange and selects it', () => {
    const s = started()
    expect(s.exchanges).toHaveLength(1)
    expect(s.exchanges[0]).toMatchObject({ question: 'Puka targets?', answer: '', running: true })
    expect(s.selected).toBe(0)
  })

  it('a done/failed step replaces its started entry', () => {
    let s = chatReducer(started(), { type: 'event', event: 'step', data: step('started') })
    s = chatReducer(s, { type: 'event', event: 'step', data: step('failed', 'bad column') })
    expect(s.exchanges[0].steps).toHaveLength(1)
    expect(s.exchanges[0].steps[0].status).toBe('failed')
  })

  it('tokens append to the answer', () => {
    let s = chatReducer(started(), { type: 'event', event: 'token', data: { text: 'Lean ' } })
    s = chatReducer(s, { type: 'event', event: 'token', data: { text: 'Nacua.' } })
    expect(s.exchanges[0].answer).toBe('Lean Nacua.')
  })

  it('sources are added', () => {
    const src = { n: 1, kind: 'stat' as const, label: 'T', columns: ['a'], rows: [[1]], row_count: 1, truncated: false }
    const s = chatReducer(started(), { type: 'event', event: 'source', data: src })
    expect(s.exchanges[0].sources).toEqual([src])
  })

  it('done stops running and keeps the totals', () => {
    const done = { ttft_ms: 900, total_ms: 3000, cost_usd: 0.04, input_tokens: 1, output_tokens: 1 }
    const s = chatReducer(started(), { type: 'event', event: 'done', data: done })
    expect(s.exchanges[0].running).toBe(false)
    expect(s.exchanges[0].done).toEqual(done)
  })

  it('error sets the message and keeps the partial answer', () => {
    let s = chatReducer(started(), { type: 'event', event: 'token', data: { text: 'Partial' } })
    s = chatReducer(s, { type: 'event', event: 'error', data: { message: 'Try again.' } })
    expect(s.exchanges[0]).toMatchObject({ answer: 'Partial', error: 'Try again.', running: false })
  })

  it('stopped marks the exchange as no longer running', () => {
    const s = chatReducer(started(), { type: 'stopped' })
    expect(s.exchanges[0].running).toBe(false)
    expect(s.exchanges[0].stopped).toBe(true)
  })

  it('events go to the latest exchange even when an older one is selected', () => {
    let s = chatReducer(started(), { type: 'event', event: 'done', data: { ttft_ms: 1, total_ms: 1, cost_usd: 0, input_tokens: 0, output_tokens: 0 } })
    s = chatReducer(s, { type: 'ask', question: 'second' })
    s = chatReducer(s, { type: 'select', index: 0 })
    s = chatReducer(s, { type: 'event', event: 'token', data: { text: 'x' } })
    expect(s.exchanges[1].answer).toBe('x')
    expect(s.selected).toBe(0)
  })

  it('reset clears the chat', () => {
    expect(chatReducer(started(), { type: 'reset' })).toEqual(initialChat)
  })
})
