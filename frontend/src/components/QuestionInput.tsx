import { useState } from 'react'

const MAX = 500

export function QuestionInput(props: {
  placeholder: string
  disabled?: boolean
  onAsk: (q: string) => void
}) {
  const [text, setText] = useState('')
  const submit = () => {
    const q = text.trim()
    if (!q || props.disabled) return
    props.onAsk(q)
    setText('')
  }
  return (
    <form
      className="ask"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <textarea
        value={text}
        maxLength={MAX}
        rows={1}
        placeholder={props.placeholder}
        aria-label="Your question"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      {text.length > MAX - 100 && <span className="count">{MAX - text.length}</span>}
      <button type="submit" disabled={props.disabled || !text.trim()} aria-label="Ask">
        →
      </button>
    </form>
  )
}
