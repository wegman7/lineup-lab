import { useEffect } from 'react'
import type { Exchange } from '../chatReducer'
import { StatCard } from './StatCard'
import { StepList } from './StepList'

export type Tab = 'hood' | 'sources'

export function Inspector(props: {
  exchange: Exchange | undefined
  tab: Tab
  highlight: number | null
  onTab: (t: Tab) => void
}) {
  const x = props.exchange
  useEffect(() => {
    if (props.tab === 'sources' && props.highlight != null) {
      document.getElementById(`source-${props.highlight}`)?.scrollIntoView({ block: 'nearest' })
    }
  }, [props.tab, props.highlight])

  return (
    <aside className="inspector" aria-label="Inspector">
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={props.tab === 'hood'} onClick={() => props.onTab('hood')}>
          Under the hood
        </button>
        <button role="tab" aria-selected={props.tab === 'sources'} onClick={() => props.onTab('sources')}>
          Sources{x?.sources.length ? ` (${x.sources.length})` : ''}
        </button>
      </div>
      <div className="tab-body">
        {!x ? null : props.tab === 'hood' ? (
          <StepList steps={x.steps} done={x.done} />
        ) : x.sources.length ? (
          x.sources.map((s) => <StatCard key={s.n} source={s} highlighted={s.n === props.highlight} />)
        ) : (
          <p className="muted">No sources for this answer.</p>
        )}
      </div>
    </aside>
  )
}
