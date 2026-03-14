import { useState } from 'react'
import { ChevronDown, ChevronRight, FileCode, MessageCircle } from 'lucide-react'

function parseSeverity(body) {
  if (!body) return null
  const match = body.match(/^\*\*(\w+)\*\*[*:]?\s*/i)
  if (!match) return null
  const level = match[1].toUpperCase()
  if (level === 'HIGH' || level === 'CRITICAL') return { level, color: 'text-[var(--red)]', bg: 'bg-[var(--red-dim)]' }
  if (level === 'MEDIUM') return { level, color: 'text-[var(--yellow)]', bg: 'bg-[var(--yellow-dim)]' }
  if (level === 'LOW' || level === 'INFO') return { level, color: 'text-[var(--blue)]', bg: 'bg-[var(--blue-dim)]' }
  return null
}

function formatCommentBody(body) {
  if (!body) return ''
  // Strip leading severity marker like **HIGH**: or **MEDIUM**:
  let text = body.replace(/^\*\*\w+\*\*[*:]?\s*/i, '')

  // Basic inline formatting
  // Code blocks
  text = text.replace(/```[\s\S]*?```/g, (match) => {
    const code = match.replace(/```\w*\n?/, '').replace(/```$/, '').trim()
    return `\n<code-block>${code}</code-block>\n`
  })
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<inline-code>$1</inline-code>')
  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  return text
}

function CommentBody({ body }) {
  const formatted = formatCommentBody(body)
  const parts = formatted.split(/(<code-block>[\s\S]*?<\/code-block>|<inline-code>.*?<\/inline-code>|<strong>.*?<\/strong>)/g)

  return (
    <div className="text-[10px] text-[var(--text-dim)] leading-relaxed whitespace-pre-wrap">
      {parts.map((part, i) => {
        if (part.startsWith('<code-block>')) {
          const code = part.replace(/<\/?code-block>/g, '')
          return (
            <pre key={i} className="my-1.5 p-2 bg-[var(--surface)] border border-[var(--border-subtle)] rounded text-[9px] font-mono overflow-x-auto text-[var(--text-dim)]">
              {code}
            </pre>
          )
        }
        if (part.startsWith('<inline-code>')) {
          const code = part.replace(/<\/?inline-code>/g, '')
          return (
            <code key={i} className="px-1 py-px bg-[var(--surface)] border border-[var(--border-subtle)] rounded text-[9px] font-mono text-[var(--accent)]">
              {code}
            </code>
          )
        }
        if (part.startsWith('<strong>')) {
          const text = part.replace(/<\/?strong>/g, '')
          return <strong key={i} className="font-semibold text-[var(--text)]">{text}</strong>
        }
        // Handle newlines as separate lines for plain text
        return part.split('\n').map((line, j, arr) => (
          <span key={`${i}-${j}`}>
            {line}
            {j < arr.length - 1 && <br />}
          </span>
        ))
      })}
    </div>
  )
}

function ThreadCard({ thread, index }) {
  const comments = thread.comments || []
  // If no comments array, try to use body/comment directly
  const hasComments = comments.length > 0
  const firstComment = hasComments ? comments[0] : null
  const severity = firstComment ? parseSeverity(firstComment.body) : null

  return (
    <div className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg overflow-hidden">
      {/* File location header */}
      {thread.path && (
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-raised)]">
          <FileCode size={10} className="text-[var(--text-muted)] flex-shrink-0" />
          <span className="text-[10px] font-mono text-[var(--text-dim)] truncate">
            {thread.path}
            {thread.line && <span className="text-[var(--accent)]">:{thread.line}</span>}
          </span>
          {severity && (
            <span className={`ml-auto text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${severity.color} ${severity.bg}`}>
              {severity.level}
            </span>
          )}
        </div>
      )}

      {/* Comments */}
      <div className="divide-y divide-[var(--border-subtle)]">
        {hasComments ? (
          comments.map((comment, j) => (
            <div key={j} className="px-3 py-2.5">
              <div className="flex items-center gap-1.5 mb-1.5">
                <MessageCircle size={9} className="text-[var(--text-muted)]" />
                <span className="text-[9px] font-semibold text-[var(--text)]">
                  {comment.author || 'unknown'}
                </span>
              </div>
              <CommentBody body={comment.body} />
            </div>
          ))
        ) : (
          <div className="px-3 py-2.5">
            <CommentBody body={thread.body || thread.comment || JSON.stringify(thread)} />
          </div>
        )}
      </div>
    </div>
  )
}

export function ReviewThreads({ threads }) {
  const [open, setOpen] = useState(false)

  if (!threads || threads.length === 0) return null

  // Count total comments across threads
  const totalComments = threads.reduce((sum, t) => sum + (t.comments?.length || 1), 0)

  return (
    <div className="mt-2.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] hover:text-[var(--text-dim)] transition-colors font-medium"
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {threads.length} review thread{threads.length !== 1 ? 's' : ''}
        <span className="text-[var(--text-muted)]">
          ({totalComments} comment{totalComments !== 1 ? 's' : ''})
        </span>
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {threads.map((thread, i) => (
            <ThreadCard key={thread.id ?? `${thread.path}-${thread.line}-${i}`} thread={thread} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}
