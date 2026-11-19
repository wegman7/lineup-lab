import { useEffect, useReducer, useRef, useState } from 'react'
import { fetchMeta, streamChat } from './api/chat'
import type { Meta } from './api/types'
import { chatReducer, initialChat } from './chatReducer'
import { Conversation } from './components/Conversation'
import { Inspector, type Tab } from './components/Inspector'
import { Landing } from './components/Landing'

export default function App() {
  const [chat, dispatch] = useReducer(chatReducer, initialChat)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaError, setMetaError] = useState(false)
  const [tab, setTab] = useState<Tab>('hood')
  const [highlight, setHighlight] = useState<number | null>(null)
  const chatId = useRef<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const running = chat.exchanges.some((x) => x.running)

  useEffect(() => {
    fetchMeta().then(setMeta, () => setMetaError(true))
  }, [])

  async function ask(question: string) {
    if (running) return
    dispatch({ type: 'ask', question })
    setTab('hood')
    setHighlight(null)
    const controller = new AbortController()
    abort.current = controller
    try {
      const r = await streamChat(question, chatId.current, controller.signal, (e) =>
        dispatch({ type: 'event', ...e }),
      )
      chatId.current = r.chatId ?? chatId.current
    } catch {
      if (controller.signal.aborted) dispatch({ type: 'stopped' })
      else
        dispatch({
          type: 'event',
          event: 'error',
          data: { message: 'Lost the connection. Please try again.' },
        })
    } finally {
      dispatch({ type: 'stopped' }) // no-op unless the stream ended without done/error
      abort.current = null
    }
  }

  function newChat() {
    abort.current?.abort()
    chatId.current = null
    dispatch({ type: 'reset' })
  }

  const started = chat.exchanges.length > 0
  return (
    <div className="app">
      <header>
        <button className="brand" onClick={newChat}>
          Lineup Lab
        </button>
        <nav>
          <span className="muted" title="Coming soon">How it works</span>
          <span className="muted" title="Coming soon">Eval results</span>
          <span className="muted" title="Coming soon">GitHub</span>
        </nav>
      </header>
      {!started ? (
        <Landing meta={meta} metaError={metaError} onAsk={ask} />
      ) : (
        <div className="panes">
          <Conversation
            exchanges={chat.exchanges}
            selected={chat.selected}
            running={running}
            onSelect={(i) => dispatch({ type: 'select', index: i })}
            onCite={(i, n) => {
              dispatch({ type: 'select', index: i })
              setTab('sources')
              setHighlight(n)
            }}
            onAsk={ask}
            onStop={() => abort.current?.abort()}
            onRetry={ask}
            onNewChat={newChat}
          />
          <Inspector exchange={chat.exchanges[chat.selected]} tab={tab} highlight={highlight} onTab={setTab} />
        </div>
      )}
    </div>
  )
}
