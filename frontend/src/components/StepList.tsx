import type { DoneEvent, StepEvent } from '../api/types'

const ICON = { started: '…', done: '✓', failed: '✗' } as const

function Detail({ step }: { step: StepEvent }) {
  const d = step.detail
  return (
    <div className="step-detail">
      {typeof d.reason === 'string' && <p>{d.reason}</p>}
      {Array.isArray(d.resolutions) &&
        (d.resolutions as { text: string; status: string; name: string | null; candidates: string[] }[]).map(
          (r) => (
            <p key={r.text}>
              “{r.text}” → {r.name ?? r.status}
              {r.status !== 'resolved' && r.candidates.length > 0 && (
                <span className="muted"> ({r.status}: {r.candidates.join(', ')})</span>
              )}
            </p>
          ),
        )}
      {typeof d.sql === 'string' && <pre>{d.sql}</pre>}
      {typeof d.error === 'string' && <p className="error">{d.error}</p>}
      {typeof d.model === 'string' && (
        <p className="muted">
          {d.model} · {String(d.input_tokens)} in / {String(d.output_tokens)} out
        </p>
      )}
    </div>
  )
}

export function StepList(props: { steps: StepEvent[]; done?: DoneEvent }) {
  if (!props.steps.length) return <p className="muted">Steps appear here as the agent works.</p>
  return (
    <ol className="steps">
      {props.steps.map((s) => (
        <li key={s.id} className={`step ${s.status}`}>
          <details open={s.kind === 'sql' || s.status === 'failed'}>
            <summary>
              <span className="icon" aria-label={s.status}>
                {ICON[s.status]}
              </span>
              <span className="summary-text">{s.summary}</span>
              {s.duration_ms != null && <span className="muted small">{s.duration_ms}ms</span>}
            </summary>
            <Detail step={s} />
          </details>
        </li>
      ))}
      {props.done && (
        <li className="step total muted small">
          Total {(props.done.total_ms / 1000).toFixed(1)}s · {props.done.input_tokens.toLocaleString()} in /{' '}
          {props.done.output_tokens.toLocaleString()} out · ${props.done.cost_usd.toFixed(4)}
        </li>
      )}
    </ol>
  )
}
