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

// Sentinel delimiters use null bytes (\x00) which cannot appear in GitHub
// comment text, preventing collisions with user-authored content.
const S_CODE_BLOCK_OPEN = '\x00CODE_BLOCK\x00'
const S_CODE_BLOCK_CLOSE = '\x00/CODE_BLOCK\x00'
const S_INLINE_CODE_OPEN = '\x00INLINE_CODE\x00'
const S_INLINE_CODE_CLOSE = '\x00/INLINE_CODE\x00'
const S_STRONG_OPEN = '\x00STRONG\x00'
const S_STRONG_CLOSE = '\x00/STRONG\x00'

function formatCommentBody(body) {
  if (!body) return ''
  // Strip leading severity marker like **HIGH**: or **MEDIUM**: but only for
  // known severity keywords so that legitimate bold prefixes such as
  // **Note**: or **Warning**: are preserved unchanged.
  let text = body.replace(/^\*\*(HIGH|CRITICAL|MEDIUM|LOW|INFO)\*\*[*:]?\s*/i, '')

  // Basic inline formatting using null-byte sentinels
  // Code blocks
  text = text.replace(/```[\s\S]*?```/g, (match) => {
    const code = match.replace(/```\w*\n?/, '').replace(/```$/, '').trim()
    return `\n${S_CODE_BLOCK_OPEN}${code}${S_CODE_BLOCK_CLOSE}\n`
  })
  // Inline code
  text = text.replace(/`([^`]+)`/g, `${S_INLINE_CODE_OPEN}$1${S_INLINE_CODE_CLOSE}`)
  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, `${S_STRONG_OPEN}$1${S_STRONG_CLOSE}`)

  return text
}

function CommentBody({ body }) {
  const formatted = formatCommentBody(body)
  const sentinelPattern = new RegExp(
    `(${S_CODE_BLOCK_OPEN}[\\s\\S]*?${S_CODE_BLOCK_CLOSE}` +
    `|${S_INLINE_CODE_OPEN}.*?${S_INLINE_CODE_CLOSE}` +
    `|${S_STRONG_OPEN}.*?${S_STRONG_CLOSE})`,
    'g'
  )
  const parts = formatted.split(sentinelPattern)

  return (
    <div className="text-[10px] text-[var(--text-dim)] leading-relaxed whitespace-pre-wrap">
      {parts.map((part, i) => {
        if (part.startsWith(S_CODE_BLOCK_OPEN)) {
          const code = part.slice(S_CODE_BLOCK_OPEN.length, -S_CODE_BLOCK_CLOSE.length)
          return (
            <pre key={i} className="my-1.5 p-2 bg-[var(--surface)] border border-[var(--border-subtle)] rounded text-[9px] font-mono overflow-x-auto text-[var(--text-dim)]">
              {code}
            </pre>
          )
        }
        if (part.startsWith(S_INLINE_CODE_OPEN)) {
          const code = part.slice(S_INLINE_CODE_OPEN.length, -S_INLINE_CODE_CLOSE.length)
          return (
            <code key={i} className="px-1 py-px bg-[var(--surface)] border border-[var(--border-subtle)] rounded text-[9px] font-mono text-[var(--accent)]">
              {code}
            </code>
          )
        }
        if (part.startsWith(S_STRONG_OPEN)) {
          const text = part.slice(S_STRONG_OPEN.length, -S_STRONG_CLOSE.length)
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
