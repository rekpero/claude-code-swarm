import { useState } from 'react'
import { ChevronDown, ChevronRight, FileCode } from 'lucide-react'

export function ReviewThreads({ threads }) {
  const [open, setOpen] = useState(false)

  if (!threads || threads.length === 0) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] text-[var(--text-dim)] hover:text-[var(--text)] transition-colors"
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {threads.length} review thread{threads.length !== 1 ? 's' : ''}
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {threads.map((thread, i) => (
            <div key={thread.id ?? `${thread.path}-${thread.line}-${i}`} className="bg-[var(--bg)] border border-[var(--border)] rounded-md p-3">
              {thread.path && (
                <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-dim)] mb-1.5">
                  <FileCode size={10} />
                  <span>{thread.path}</span>
                  {thread.line && <span>:{thread.line}</span>}
                </div>
              )}
              <p className="text-[11px] text-[var(--text)] leading-relaxed">
                {thread.body || thread.comment || JSON.stringify(thread)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
