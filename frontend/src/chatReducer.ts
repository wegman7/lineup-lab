import type { DoneEvent, ServerEvent, SourceEvent, StepEvent } from './api/types'

export interface Exchange {
  question: string
  answer: string
  steps: StepEvent[]
  sources: SourceEvent[]
  running: boolean
  done?: DoneEvent
  error?: string
  stopped?: boolean
}

export interface ChatState {
  exchanges: Exchange[]
  selected: number // which exchange the inspector shows
}

export type ChatAction =
  | { type: 'ask'; question: string }
  | ({ type: 'event' } & ServerEvent)
  | { type: 'stopped' }
  | { type: 'select'; index: number }
  | { type: 'reset' }

export const initialChat: ChatState = { exchanges: [], selected: -1 }

function updateLast(state: ChatState, f: (x: Exchange) => Exchange): ChatState {
  if (!state.exchanges.length) return state
  const exchanges = state.exchanges.slice()
  exchanges[exchanges.length - 1] = f(exchanges[exchanges.length - 1])
  return { ...state, exchanges }
}

function applyEvent(x: Exchange, e: ServerEvent): Exchange {
  switch (e.event) {
    case 'step': {
      const i = x.steps.findIndex((s) => s.id === e.data.id)
      const steps = i === -1 ? [...x.steps, e.data] : x.steps.map((s, j) => (j === i ? e.data : s))
      return { ...x, steps }
    }
    case 'token':
      return { ...x, answer: x.answer + e.data.text }
    case 'source':
      return { ...x, sources: [...x.sources, e.data] }
    case 'done':
      return { ...x, done: e.data, running: false }
    case 'error':
      return { ...x, error: e.data.message, running: false }
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'ask': {
      const fresh: Exchange = { question: action.question, answer: '', steps: [], sources: [], running: true }
      return { exchanges: [...state.exchanges, fresh], selected: state.exchanges.length }
    }
    case 'event': {
      const { type: _type, ...event } = action
      return updateLast(state, (x) => applyEvent(x, event as ServerEvent))
    }
    case 'stopped':
      return updateLast(state, (x) => (x.running ? { ...x, running: false, stopped: true } : x))
    case 'select':
      return { ...state, selected: action.index }
    case 'reset':
      return initialChat
  }
}
