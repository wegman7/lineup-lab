import type { Meta } from '../api/types'
import { QuestionInput } from './QuestionInput'

export function Landing(props: { meta: Meta | null; metaError: boolean; onAsk: (q: string) => void }) {
  const c = props.meta?.coverage
  const seasons = c ? `${c.seasons[0]}–${c.seasons[c.seasons.length - 1]}` : ''
  return (
    <main className="landing">
      <p className="tagline">Fantasy football answers backed by the numbers and what analysts said.</p>
      <section className="coverage" aria-label="Data coverage">
        {c ? (
          <>
            <div>📊 Stats: {seasons} seasons, through Week {c.as_of_week}</div>
            <div>🎙 Podcasts: coming soon</div>
            <div className="muted">Data as of Week {c.as_of_week}, {c.as_of_season}</div>
          </>
        ) : (
          <div className="muted">{props.metaError ? 'Couldn’t load data coverage.' : 'Loading…'}</div>
        )}
      </section>
      <section className="examples" aria-label="Example questions">
        {props.meta?.examples.map((g) => (
          <div className="group" key={g.group}>
            <span className="group-name">{g.group}</span>
            <div className="chips">
              {g.questions.map((q) => (
                <button key={q} className="chip" onClick={() => props.onAsk(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ))}
      </section>
      <QuestionInput placeholder="Ask about a player or a stat…" onAsk={props.onAsk} />
    </main>
  )
}
