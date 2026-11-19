import type { SourceEvent } from '../api/types'

const fmt = (v: unknown) => (v == null ? '–' : String(v))

export function StatCard(props: { source: SourceEvent; highlighted: boolean }) {
  const s = props.source
  return (
    <div className={`card${props.highlighted ? ' highlighted' : ''}`} id={`source-${s.n}`}>
      <div className="card-head">
        <span className="badge">[{s.n}]</span> 📊 {s.label}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {s.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {s.rows.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j} className={typeof v === 'number' ? 'num' : ''}>
                    {fmt(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.truncated && (
        <div className="muted small">
          Showing {s.rows.length} of {s.row_count} rows
        </div>
      )}
    </div>
  )
}
