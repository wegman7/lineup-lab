// Mirrors backend/src/lineup_lab/agent/events.py exactly (the SSE contract).

export type StepKind = 'route' | 'resolve' | 'sql' | 'answer' | 'decline'
export type StepStatus = 'started' | 'done' | 'failed'

export interface StepEvent {
  id: string
  kind: StepKind
  status: StepStatus
  summary: string
  detail: Record<string, unknown>
  duration_ms: number | null
}

export interface TokenEvent {
  text: string
}

export interface SourceEvent {
  n: number
  kind: 'stat'
  label: string
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
}

export interface DoneEvent {
  ttft_ms: number | null
  total_ms: number
  cost_usd: number
  input_tokens: number
  output_tokens: number
}

export interface ErrorEvent {
  message: string
}

export type ServerEvent =
  | { event: 'step'; data: StepEvent }
  | { event: 'token'; data: TokenEvent }
  | { event: 'source'; data: SourceEvent }
  | { event: 'done'; data: DoneEvent }
  | { event: 'error'; data: ErrorEvent }

export interface Coverage {
  seasons: number[]
  as_of_season: number
  as_of_week: number
}

export interface Meta {
  coverage: Coverage
  examples: { group: string; questions: string[] }[]
}
