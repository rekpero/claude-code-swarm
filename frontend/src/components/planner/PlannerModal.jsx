import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Plus, ChevronRight, ChevronDown, Layers } from 'lucide-react'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { usePlanning } from '../../hooks/usePlanning'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useWorkspaces } from '../../hooks/useWorkspaces'
import { formatDistanceToNow } from 'date-fns'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

function renderMarkdown(text) {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text))
}

function eventIcon(eventType) {
  if (eventType === 'tool_use') return '\u{1f50d}'
  if (eventType === 'tool_result') return '\u2713'
  if (eventType === 'thinking') return '\u{1f4ad}'
  if (eventType === 'info') return '\u25c8'
  if (eventType === 'text') return '\u25cb'
  return '\u2699\ufe0f'
}

function eventColor(eventType) {
  switch (eventType) {
    case 'tool_use': return 'text-[var(--yellow)]'
    case 'tool_result': return 'text-[var(--green)]'
    case 'thinking': return 'text-[var(--accent)]'
    case 'text': return 'text-[var(--text-dim)]'
    case 'info': return 'text-[var(--blue)]'
    default: return 'text-[var(--text-muted)]'
  }
}

// Whether this event type's text should wrap rather than truncate
function eventWraps(eventType) {
  return eventType === 'thinking' || eventType === 'text'
}

function SessionSidebar({ sessions, activeSessionId, onSelect, onNew, onDelete }) {
  return (
    <div className="w-[220px] min-w-[220px] border-r border-[var(--border)] flex flex-col bg-[var(--bg)]">
      <div className="px-3.5 py-3 flex justify-between items-center border-b border-[var(--border)]">
        <span className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-semibold">Sessions</span>
        <Button size="sm" onClick={onNew}>
          <Plus size={9} /> New
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {sessions.length === 0 ? (
          <div className="px-3.5 py-6 text-[10px] text-[var(--text-muted)] text-center">No sessions yet</div>
        ) : (
          sessions.map(s => {
            const isActive = s.id === activeSessionId
            const preview = s.first_message || s.title || 'Untitled session'
            const truncated = preview.length > 55 ? preview.slice(0, 52) + '\u2026' : preview
            const statusColors = {
              completed: 'bg-[var(--green-dim)] text-[var(--green)]',
              active: 'bg-[var(--accent-dim)] text-[var(--accent)]',
              generating: 'bg-[var(--yellow-dim)] text-[var(--yellow)]',
              error: 'bg-[var(--red-dim)] text-[var(--red)]',
            }
            const statusClass = statusColors[s.status] || statusColors.active
            const statusLabel = s.status === 'completed' ? '\u2713' : (s.status || 'active')
            return (
              <div
                key={s.id}
                className={`group px-3.5 py-2.5 cursor-pointer border-l-2 transition-all ${
                  isActive
                    ? 'bg-[var(--accent-dim)] border-l-[var(--accent)]'
                    : 'border-l-transparent hover:bg-[var(--surface-hover)]'
                }`}
                onClick={() => onSelect(s.id)}
              >
                <div className="text-[11px] text-[var(--text-dim)] truncate mb-1 font-medium">{truncated}</div>
                <div className="flex justify-between items-center text-[9px] text-[var(--text-muted)]">
                  <span className="flex items-center gap-1.5">
                    <span className={`inline-block px-1.5 py-0 rounded text-[8px] font-bold uppercase tracking-wider ${statusClass}`}>
                      {statusLabel}
                    </span>
                    {s.updated_at && formatDistanceToNow(new Date(s.updated_at), { addSuffix: true })}
                  </span>
                  <button
                    className="opacity-0 group-hover:opacity-50 hover:!opacity-100 text-[var(--red)] text-xs leading-none transition-opacity"
                    onClick={(e) => { e.stopPropagation(); onDelete(s.id) }}
                    title="Delete"
                  >
                    &times;
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

/**
 * Streaming analysis steps — shown while Claude is generating.
 * Each event animates in. When generation completes, collapses into
 * a clickable "View analysis steps (N)" summary.
 */
function StreamingSteps({ events, isGenerating }) {
  const [expanded, setExpanded] = useState(true)
  const listRef = useRef(null)

  // Separate non-draft events for the step list
  const stepEvents = events.filter(e => e.event_type !== 'draft')
  if (stepEvents.length === 0) return null

  const lastStep = stepEvents[stepEvents.length - 1]
  const lastLabel = lastStep?.summary?.length > 70
    ? lastStep.summary.slice(0, 67) + '\u2026'
    : (lastStep?.summary || 'Analyzing\u2026')

  // Auto-scroll the event list to bottom when new events arrive
  useEffect(() => {
    if (expanded && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [stepEvents.length, expanded])

  return (
    <div className="bg-[var(--accent-dim)] border border-[var(--accent-border)] rounded-lg my-2.5 overflow-hidden">
      {/* Header — clickable to toggle */}
      <div
        className="flex items-center gap-2 px-3.5 py-2.5 cursor-pointer hover:bg-[rgba(139,92,246,0.06)] transition-colors"
        onClick={() => setExpanded(v => !v)}
      >
        {isGenerating ? (
          <Spinner size={10} />
        ) : (
          <ChevronRight
            size={10}
            className={`text-[var(--accent)] transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}
          />
        )}
        <span className="text-[10px] text-[var(--accent)] font-medium flex-1 truncate font-mono">
          {isGenerating
            ? lastLabel
            : `View analysis steps (${stepEvents.length})`
          }
        </span>
        {!isGenerating && (
          <span className="text-[9px] text-[var(--text-muted)]">
            {stepEvents.length} step{stepEvents.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Event list */}
      {expanded && (
        <div
          ref={listRef}
          className="px-3.5 pb-3 max-h-[240px] overflow-y-auto"
        >
          <div className="border-t border-[rgba(139,92,246,0.1)] pt-2 space-y-px">
            {stepEvents.map((ev, i) => {
              const icon = eventIcon(ev.event_type)
              const color = eventColor(ev.event_type)
              const wraps = eventWraps(ev.event_type)

              return (
                <div
                  key={ev.id || i}
                  className="flex items-start gap-2 py-1 animate-fade-in"
                  style={{ animationDelay: `${Math.min(i * 20, 200)}ms` }}
                >
                  <span className="text-[11px] flex-shrink-0 mt-px select-none">{icon}</span>
                  <span
                    className={`text-[10px] font-mono leading-relaxed ${color} ${
                      wraps
                        ? 'whitespace-pre-wrap break-words italic'
                        : 'truncate'
                    }`}
                  >
                    {ev.summary}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Live draft — growing plan preview rendered with markdown.
 * Shows while Claude is still generating, with a violet left accent border.
 */
function LiveDraft({ events }) {
  const drafts = events.filter(e => e.event_type === 'draft')
  if (drafts.length === 0) return null
  const lastDraft = drafts[drafts.length - 1]
  return (
    <div className="my-2.5 relative">
      {/* Accent left border */}
      <div className="absolute left-0 top-0 bottom-0 w-[2px] rounded-full bg-[var(--accent)] opacity-50" />
      <div
        className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg ml-3 p-4 text-[11px] leading-relaxed opacity-75 transition-opacity"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(lastDraft.summary) }}
      />
    </div>
  )
}

/**
 * Inline "Create Issue" controls embedded in each assistant plan message.
 */
function PlanIssueAction({ messageIndex, planning }) {
  const [showTitle, setShowTitle] = useState(false)
  const [title, setTitle] = useState('')
  const issueResult = planning.issueResults[messageIndex]
  const isCreating = planning.creatingIssue === messageIndex
  const isOtherCreating = planning.creatingIssue != null && planning.creatingIssue !== messageIndex

  if (issueResult) {
    return (
      <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-2 text-[10px] text-[var(--green)] font-medium">
          <span className="w-4 h-4 rounded-full bg-[var(--green-dim)] flex items-center justify-center text-[9px]">{'\u2713'}</span>
          Issue created:{' '}
          {issueResult.url?.startsWith('https://') ? (
            <a href={issueResult.url} target="_blank" rel="noopener noreferrer" className="underline">
              {issueResult.url}
            </a>
          ) : (
            issueResult.number != null ? `#${issueResult.number}` : 'created'
          )}
        </div>
        {issueResult.title && (
          <div className="mt-1 text-[9px] text-[var(--text-muted)]">{issueResult.title}</div>
        )}
      </div>
    )
  }

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          loading={isCreating}
          disabled={isCreating || isOtherCreating || planning.generating}
          onClick={async () => {
            const result = await planning.createIssue(messageIndex, title.trim())
            if (result?.error) {
              alert('Failed to create issue: ' + result.error)
            }
          }}
        >
          Create Issue from this Plan
        </Button>
        {!isCreating && (
          <button
            className="text-[9px] text-[var(--text-muted)] hover:text-[var(--text-dim)] transition-colors font-medium"
            onClick={() => setShowTitle(v => !v)}
          >
            {showTitle ? '\u25bc' : '\u25b6'} title
          </button>
        )}
      </div>
      {showTitle && (
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Leave blank to auto-generate title"
          className="mt-2 w-full bg-[var(--surface)] border border-[var(--border)] rounded p-2 text-[10px] font-mono text-[var(--text)] focus:outline-none focus:border-[var(--accent-border)] placeholder:text-[var(--text-muted)] transition-colors"
        />
      )}
    </div>
  )
}

function PlannerWorkspacePicker({ workspaceId, onChange }) {
  const { data } = useWorkspaces()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const workspaces = data?.workspaces || []
  const selected = workspaces.find(w => w.id === workspaceId)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  if (workspaces.length === 0) {
    return (
      <span className="text-[10px] text-[var(--text-muted)] italic">No workspaces configured</span>
    )
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-md text-[10px] hover:border-[var(--text-muted)] transition-colors"
      >
        {selected ? (
          <>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              selected.status === 'active' ? 'bg-[var(--green)]' : 'bg-[var(--yellow)]'
            }`} />
            <span className="font-medium truncate max-w-[160px]">{selected.name || selected.repo_url}</span>
          </>
        ) : (
          <span className="text-[var(--red)]">Select workspace</span>
        )}
        <ChevronDown size={9} className="text-[var(--text-muted)]" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-[0_8px_24px_rgba(0,0,0,0.5)] min-w-[220px] z-50 overflow-hidden animate-fade-in">
          {workspaces.map(ws => (
            <div
              key={ws.id}
              className={`flex items-center gap-2 px-3 py-2 cursor-pointer text-[10px] hover:bg-[var(--surface-hover)] transition-colors ${
                workspaceId === ws.id ? 'bg-[var(--accent-dim)]' : ''
              }`}
              onClick={() => { onChange(ws.id); setOpen(false) }}
            >
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                ws.status === 'active' ? 'bg-[var(--green)]' : 'bg-[var(--yellow)]'
              }`} />
              <span className="flex-1 truncate font-medium">{ws.name || ws.repo_url}</span>
              <span className="text-[var(--text-muted)] text-[8px] font-mono truncate max-w-[80px]">
                {ws.repo_url?.replace(/^https?:\/\/github\.com\//, '')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PlannerModal({ open, onClose }) {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data: wsData } = useWorkspaces()
  const workspaces = wsData?.workspaces || []

  // Planner has its own workspace state. Reset to the current global
  // workspace each time the modal opens so it matches what the user sees.
  const [plannerWsId, setPlannerWsId] = useState(null)
  const prevOpenRef = useRef(false)

  // On each open transition (false -> true), sync to global workspace
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      const initial = selectedWorkspaceId || (workspaces.length > 0 ? workspaces[0].id : null)
      setPlannerWsId(initial)
    }
    prevOpenRef.current = open
  }, [open, selectedWorkspaceId, workspaces])

  // Derive the effective workspace ID for the first render before useEffect fires
  const effectiveWsId = plannerWsId
    || selectedWorkspaceId
    || (workspaces.length > 0 ? workspaces[0].id : null)

  const planning = usePlanning(effectiveWsId)
  const { loadSessions } = planning
  const chatRef = useRef(null)
  const inputRef = useRef(null)
  const [inputValue, setInputValue] = useState('')

  useEffect(() => {
    if (open && effectiveWsId) {
      loadSessions()
      const id = setTimeout(() => inputRef.current?.focus(), 100)
      return () => clearTimeout(id)
    }
  }, [open, effectiveWsId, loadSessions])

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [planning.messages, planning.streamEvents])

  const handleSend = () => {
    if (!inputValue.trim() || planning.generating) return
    if (!effectiveWsId) {
      alert('Please select a workspace first.')
      return
    }
    planning.sendMessage(inputValue.trim())
    setInputValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleDeleteSession = (sid) => {
    if (!confirm('Delete this planning session?')) return
    planning.deleteSession(sid)
  }

  const latestStepSummary = (() => {
    const steps = (planning.streamEvents || []).filter(e => e.event_type !== 'draft')
    if (steps.length === 0) return null
    const last = steps[steps.length - 1]
    if (!last?.summary) return null
    return last.summary.length > 80 ? last.summary.slice(0, 77) + '\u2026' : last.summary
  })()

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm animate-fade-in"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="flex rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[0_32px_80px_rgba(0,0,0,0.7),0_0_60px_var(--accent-glow)] overflow-hidden animate-fade-in"
        style={{ width: '1060px', maxWidth: '96vw', maxHeight: '88vh' }}
      >
        <SessionSidebar
          sessions={planning.sessions}
          activeSessionId={planning.sessionId}
          onSelect={(sid) => planning.resumeSession(sid)}
          onNew={() => planning.startNew()}
          onDelete={handleDeleteSession}
        />

        <div className="flex-1 flex flex-col p-6 min-w-0">
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-3">
              <h3 className="text-[14px] font-semibold tracking-tight">Plan Issue</h3>
              <span className="text-[var(--border)] text-xs">/</span>
              <PlannerWorkspacePicker
                workspaceId={effectiveWsId}
                onChange={(id) => {
                  setPlannerWsId(id)
                  planning.startNew()
                }}
              />
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-dim)] hover:bg-[var(--surface-hover)] transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          {/* Chat area */}
          <div ref={chatRef} className="flex-1 overflow-y-auto min-h-[200px] max-h-[420px] py-2">
            {planning.messages.length === 0 && !planning.generating && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-8 h-8 rounded-lg bg-[var(--accent-dim)] flex items-center justify-center mb-3">
                  <span className="text-[var(--accent)] text-sm">{'\u25c8'}</span>
                </div>
                <p className="text-[11px] text-[var(--text-muted)]">
                  Describe a feature or bug fix and Claude will analyze the codebase to create a plan.
                </p>
              </div>
            )}

            {planning.messages.map((m, i) => (
              m.role === 'user' ? (
                <div key={i} className="bg-[var(--accent-dim)] border border-[var(--accent-border)] rounded-lg p-3 my-2 text-[11px] whitespace-pre-wrap font-mono text-[var(--text)]">
                  {m.content}
                </div>
              ) : (
                <div
                  key={i}
                  className="bg-[var(--bg)] border border-[var(--border-subtle)] rounded-lg my-2 overflow-hidden"
                >
                  {/* Plan content */}
                  <div
                    className="p-4 text-[11px] leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                  />
                  {/* Embedded Create Issue action */}
                  <div className="px-4 pb-3">
                    <PlanIssueAction messageIndex={i} planning={planning} />
                  </div>
                </div>
              )
            ))}

            {/* Streaming analysis steps */}
            {(planning.streamEvents?.length > 0) && (
              <StreamingSteps
                events={planning.streamEvents}
                isGenerating={planning.generating}
              />
            )}

            {/* Live draft preview while generating */}
            {planning.generating && <LiveDraft events={planning.streamEvents} />}
          </div>

          {/* Status bar */}
          {(planning.generating || planning.creatingIssue != null) && (
            <div className="flex items-center gap-2 py-2 px-1 border-t border-[var(--border-subtle)]">
              <Spinner size={9} />
              <span className="text-[10px] text-[var(--text-muted)] font-mono truncate flex-1">
                {planning.creatingIssue != null
                  ? 'Creating GitHub issue\u2026'
                  : (latestStepSummary || 'Starting analysis\u2026')
                }
              </span>
            </div>
          )}

          {/* Input area */}
          <div className="mt-3">
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={planning.generating}
              placeholder={planning.hasPlan
                ? 'Refine the plan \u2014 your feedback will update it with full context\u2026'
                : 'Describe the feature or fix you want to implement\u2026'
              }
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg p-3 text-[11px] font-mono text-[var(--text)] resize-none focus:outline-none focus:border-[var(--accent-border)] disabled:opacity-40 placeholder:text-[var(--text-muted)] transition-colors"
              rows={3}
            />
            <div className="flex items-center gap-2 mt-2">
              <Button variant="primary" onClick={handleSend} disabled={planning.generating || !inputValue.trim()}>
                {planning.hasPlan ? 'Refine Plan' : 'Generate Plan'}
              </Button>
              {planning.generating && (
                <Button onClick={() => planning.cancelGeneration()}>Cancel</Button>
              )}
              <span className="text-[9px] text-[var(--text-muted)] ml-1">
                {navigator.platform?.includes('Mac') ? '\u2318' : 'Ctrl'}+Enter to send
              </span>
            </div>
            {planning.hasPlan && !planning.generating && (
              <p className="mt-1.5 text-[9px] text-[var(--text-muted)]">
                Refinements update the existing plan with full conversation context. Each plan above has its own "Create Issue" button.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
