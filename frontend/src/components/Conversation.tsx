import { Fragment, useEffect, useRef } from 'react'
import type { Exchange } from '../chatReducer'
import { QuestionInput } from './QuestionInput'

function AnswerText(props: { text: string; onCite: (n: number) => void }) {
  const parts = props.text.split(/(\[\d+\])/g)
  return (
    <p className="answer">
      {parts.map((p, i) => {
        const m = /^\[(\d+)\]$/.exec(p)
        return m ? (
          <button key={i} className="cite" onClick={() => props.onCite(Number(m[1]))}>
            {p}
          </button>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        )
      })}
    </p>
  )
}

function Footer({ x }: { x: Exchange }) {
  if (!x.done) return null
  const s = (ms: number | null) => (ms == null ? '–' : `${(ms / 1000).toFixed(1)}s`)
  return (
    <div className="footer">
      {s(x.done.ttft_ms)} first token · {s(x.done.total_ms)} · ${x.done.cost_usd.toFixed(3)}
    </div>
  )
}

export function Conversation(props: {
  exchanges: Exchange[]
  selected: number
  running: boolean
  onSelect: (i: number) => void
  onCite: (i: number, n: number) => void
  onAsk: (q: string) => void
  onStop: () => void
  onRetry: (q: string) => void
  onNewChat: () => void
}) {
  const end = useRef<HTMLDivElement>(null)
  const last = props.exchanges[props.exchanges.length - 1]
  useEffect(() => end.current?.scrollIntoView({ block: 'end' }), [props.exchanges.length, last?.answer])

  return (
    <section className="conversation" aria-label="Conversation">
      <div className="thread">
        {props.exchanges.map((x, i) => (
          <article
            key={i}
            className={`exchange${i === props.selected ? ' selected' : ''}`}
            onClick={() => props.onSelect(i)}
          >
            <div className="question">
              <span className="who">You</span> {x.question}
            </div>
            {x.answer ? (
              <AnswerText text={x.answer} onCite={(n) => props.onCite(i, n)} />
            ) : (
              x.running && <p className="answer muted thinking">Working on it…</p>
            )}
            {x.stopped && <p className="muted">Stopped.</p>}
            {x.error && (
              <p className="error">
                {x.error}{' '}
                <button className="link" onClick={() => props.onRetry(x.question)} disabled={props.running}>
                  Retry
                </button>
              </p>
            )}
            <Footer x={x} />
          </article>
        ))}
        <div ref={end} />
      </div>
      <div className="composer">
        {props.running ? (
          <button className="stop" onClick={props.onStop}>
            ■ Stop
          </button>
        ) : (
          <QuestionInput placeholder="Ask another question…" onAsk={props.onAsk} />
        )}
        <button className="link" onClick={props.onNewChat} disabled={props.running}>
          New chat
        </button>
      </div>
    </section>
  )
}
