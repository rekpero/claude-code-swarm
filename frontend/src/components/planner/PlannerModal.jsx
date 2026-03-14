import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  X, Plus, ChevronRight, ChevronDown,
  Search, FileText, CheckCircle2, Brain,
  Info, Terminal,
} from 'lucide-react'
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
  const html = marked.parse(text, { async: false })
  return typeof html === 'string' ? DOMPurify.sanitize(html) : ''
}

const EVENT_CONFIG = {
  tool_use:    { Icon: Search,       color: 'var(--yellow)',  bg: 'var(--yellow-dim)', label: 'Searching' },
  tool_result: { Icon: CheckCircle2, color: 'var(--green)',   bg: 'var(--green-dim)',  label: 'Result' },
  thinking:    { Icon: Brain,        color: 'var(--accent)',  bg: 'var(--accent-dim)', label: 'Thinking' },
  info:        { Icon: Info,         color: 'var(--blue)',    bg: 'var(--blue-dim)',   label: 'Info' },
  text:        { Icon: FileText,     color: 'var(--text-dim)',bg: 'rgba(255,255,255,0.04)', label: 'Output' },
}

function getEventConfig(type) {
  return EVENT_CONFIG[type] || { Icon: Terminal, color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.04)', label: type }
}

/* ─── Session sidebar ──────────────────────────────────────────────── */

function SessionSidebar({ sessions, activeSessionId, onSelect, onNew, onDelete, confirmDeleteId, onCancelDelete }) {
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
                  {confirmDeleteId === s.id ? (
                    <span className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="text-[var(--red)] text-[8px] font-bold hover:underline"
                        onClick={() => onDelete(s.id)}
                      >
                        Confirm
                      </button>
                      <button
                        className="text-[var(--text-muted)] text-[8px] hover:underline"
                        onClick={() => onCancelDelete()}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      className="opacity-0 group-hover:opacity-50 hover:!opacity-100 text-[var(--red)] text-xs leading-none transition-opacity"
                      onClick={(e) => { e.stopPropagation(); onDelete(s.id) }}
                      title="Delete"
                    >
                      &times;
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

/* ─── Activity feed — replaces StreamingSteps + status bar ─────────── */

function ActivityFeed({ events, isGenerating }) {
  const [collapsed, setCollapsed] = useState(false)
  const listRef = useRef(null)
  const userScrolledUpRef = useRef(false)

  const stepEvents = events.filter(e => e.event_type !== 'draft')

  // Track whether user has scrolled up
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const handleScroll = () => {
      const threshold = 30
      const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
      userScrolledUpRef.current = !isAtBottom
    }
    el.addEventListener('scroll', handleScroll)
    return () => el.removeEventListener('scroll', handleScroll)
  }, [collapsed])

  // Auto-scroll only if user hasn't scrolled up
  useEffect(() => {
    if (!collapsed && listRef.current && !userScrolledUpRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [stepEvents.length, collapsed])

  if (stepEvents.length === 0 && !isGenerating) return null

  // When generating with no events yet, show a pulsing indicator
  if (stepEvents.length === 0 && isGenerating) {
    return (
      <div className="flex items-center gap-2.5 py-3 px-4 my-2 rounded-lg bg-[var(--surface)]">
        <Spinner size={12} />
        <span className="text-[11px] text-[var(--text-muted)] font-mono">{'Starting analysis\u2026'}</span>
      </div>
    )
  }

  const lastStep = stepEvents[stepEvents.length - 1]
  const lastConfig = getEventConfig(lastStep?.event_type)
  const stepCount = stepEvents.length

  // Completed state — collapsed by default
  if (!isGenerating) {
    return (
      <div className="my-2 rounded-lg border border-[var(--border-subtle)] overflow-hidden">
        <button
          className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
          onClick={() => setCollapsed(v => !v)}
        >
          <ChevronRight
            size={11}
            className={`text-[var(--text-muted)] transition-transform duration-200 ${!collapsed ? 'rotate-90' : ''}`}
          />
          <span className="text-[10px] text-[var(--text-muted)] font-mono">
            Analysis complete — {stepCount} step{stepCount !== 1 ? 's' : ''}
          </span>
        </button>
        {!collapsed && (
          <div ref={listRef} className="px-2 pb-2 max-h-[200px] overflow-y-auto">
            <EventList events={stepEvents} />
          </div>
        )}
      </div>
    )
  }

  // Generating state — open by default, with live header
  return (
    <div className="my-2 rounded-lg border border-[var(--accent-border)] bg-[var(--surface)] overflow-hidden">
      {/* Live status header */}
      <div
        className="flex items-center gap-2.5 px-4 py-2.5 border-b border-[var(--border-subtle)] cursor-pointer hover:bg-[var(--surface-hover)] transition-colors"
        onClick={() => setCollapsed(v => !v)}
      >
        <Spinner size={11} />
        <lastConfig.Icon size={11} style={{ color: lastConfig.color }} className="flex-shrink-0" />
        <span className="text-[10px] font-mono flex-1 truncate" style={{ color: lastConfig.color }}>
          {lastStep?.summary || 'Analyzing\u2026'}
        </span>
        <span className="text-[9px] text-[var(--text-muted)] flex-shrink-0 tabular-nums">
          {stepCount}
        </span>
        <ChevronRight
          size={10}
          className={`text-[var(--text-muted)] transition-transform duration-200 flex-shrink-0 ${!collapsed ? 'rotate-90' : ''}`}
        />
      </div>

      {/* Scrollable event list */}
      {!collapsed && (
        <div ref={listRef} className="px-2 pb-2 max-h-[220px] overflow-y-auto">
          <EventList events={stepEvents} />
        </div>
      )}
    </div>
  )
}

function EventList({ events }) {
  return (
    <div className="pt-1">
      {events.map((ev, i) => {
        const cfg = getEventConfig(ev.event_type)
        const isThinking = ev.event_type === 'thinking' || ev.event_type === 'text'
        const isResult = ev.event_type === 'tool_result'

        return (
          <div
            key={ev.id || i}
            className={`group flex items-start gap-2.5 py-[5px] animate-slide-in ${
              isResult ? 'pl-[30px]' : 'px-2'
            }`}
            style={{ animationDelay: `${Math.min(i * 12, 120)}ms` }}
          >
            {/* Icon — results are indented under their tool_use, no icon */}
            {!isResult && (
              <span
                className="flex-shrink-0 mt-px w-[18px] h-[18px] rounded flex items-center justify-center"
                style={{ background: cfg.bg }}
              >
                <cfg.Icon size={10} style={{ color: cfg.color }} />
              </span>
            )}
            {isResult && (
              <span className="flex-shrink-0 mt-[3px] w-[6px] h-[6px] rounded-full" style={{ background: cfg.color, opacity: 0.6 }} />
            )}

            {/* Content */}
            <span
              className={`text-[10px] font-mono leading-[1.6] min-w-0 ${
                isThinking
                  ? 'whitespace-pre-wrap break-words italic text-[var(--text-muted)]'
                  : isResult
                    ? 'truncate text-[var(--text-muted)] text-[9px]'
                    : 'truncate text-[var(--text-dim)]'
              }`}
            >
              {ev.summary}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ─── Live draft (growing plan preview) ────────────────────────────── */

function LiveDraft({ events }) {
  const drafts = events.filter(e => e.event_type === 'draft')
  if (drafts.length === 0) return null
  const lastDraft = drafts[drafts.length - 1]
  return (
    <div className="my-2 relative group">
      <div className="absolute left-0 top-0 bottom-0 w-[2px] rounded-full bg-[var(--accent)] opacity-40" />
      <div
        className="ml-4 p-4 rounded-lg bg-[var(--bg)] border border-[var(--border-subtle)] text-[11px] leading-relaxed opacity-60 group-hover:opacity-80 transition-opacity prose-planner"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(lastDraft.summary) }}
      />
    </div>
  )
}

/* ─── Create Issue action ──────────────────────────────────────────── */

function PlanIssueAction({ messageIndex, planning }) {
  const [showTitle, setShowTitle] = useState(false)
  const [title, setTitle] = useState('')
  const [createError, setCreateError] = useState(null)
  const issueResult = planning.issueResults?.[messageIndex]
  const isCreating = planning.creatingIssue === messageIndex
  const isOtherCreating = planning.creatingIssue != null && planning.creatingIssue !== messageIndex

  if (issueResult) {
    return (
      <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-2 text-[10px] text-[var(--green)] font-medium">
          <CheckCircle2 size={12} />
          Issue created:{' '}
          {issueResult.url?.startsWith('https://') ? (
            <a href={issueResult.url} target="_blank" rel="noopener noreferrer" className="underline hover:no-underline">
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
            setCreateError(null)
            try {
              const result = await planning.createIssue(messageIndex, title.trim())
              if (result?.error) {
                setCreateError('Failed to create issue: ' + result.error)
              }
            } catch (err) {
              setCreateError('Failed to create issue: ' + (err?.message || 'Unknown error'))
            }
          }}
        >
          Create Issue
        </Button>
        {!isCreating && (
          <button
            className="text-[9px] text-[var(--text-muted)] hover:text-[var(--text-dim)] transition-colors font-medium"
            onClick={() => setShowTitle(v => !v)}
          >
            {showTitle ? <ChevronDown size={8} className="inline" /> : <ChevronRight size={8} className="inline" />}
            {' '}custom title
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
      {createError && (
        <p className="mt-2 text-[10px] text-[var(--red)]">{createError}</p>
      )}
    </div>
  )
}

/* ─── Workspace picker ─────────────────────────────────────────────── */

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

/* ─── Main modal ───────────────────────────────────────────────────── */

export function PlannerModal({ open, onClose }) {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { data: wsData } = useWorkspaces()
  const workspaces = wsData?.workspaces || []

  const [plannerWsId, setPlannerWsId] = useState(null)
  const prevOpenRef = useRef(false)

  useEffect(() => {
    if (open && !prevOpenRef.current) {
      const initial = selectedWorkspaceId || (workspaces.length > 0 ? workspaces[0].id : null)
      setPlannerWsId(initial)
    }
    prevOpenRef.current = open
  }, [open, selectedWorkspaceId, workspaces])

  const effectiveWsId = plannerWsId
    || selectedWorkspaceId
    || (workspaces.length > 0 ? workspaces[0].id : null)

  const planning = usePlanning(effectiveWsId)
  const { loadSessions } = planning
  const chatRef = useRef(null)
  const inputRef = useRef(null)
  const chatUserScrolledUpRef = useRef(false)
  const [inputValue, setInputValue] = useState('')
  const [wsError, setWsError] = useState(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)

  useEffect(() => {
    if (open && effectiveWsId) {
      loadSessions()
      const id = setTimeout(() => inputRef.current?.focus(), 100)
      return () => clearTimeout(id)
    }
  }, [open, effectiveWsId, loadSessions])

  // Track whether user has scrolled up in chat area
  useEffect(() => {
    const el = chatRef.current
    if (!el) return
    const handleScroll = () => {
      const threshold = 50
      const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
      chatUserScrolledUpRef.current = !isAtBottom
    }
    el.addEventListener('scroll', handleScroll)
    return () => el.removeEventListener('scroll', handleScroll)
  }, [open])

  // Auto-scroll chat only if user hasn't scrolled up
  useEffect(() => {
    if (chatRef.current && !chatUserScrolledUpRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [planning.messages, planning.streamEvents])

  const handleSend = () => {
    if (!inputValue.trim() || planning.generating) return
    if (!effectiveWsId) {
      setWsError('Please select a workspace first.')
      return
    }
    setWsError(null)
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
    if (confirmDeleteId === sid) {
      setConfirmDeleteId(null)
      planning.deleteSession(sid)
    } else {
      setConfirmDeleteId(sid)
    }
  }

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
          confirmDeleteId={confirmDeleteId}
          onCancelDelete={() => setConfirmDeleteId(null)}
        />

        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex justify-between items-center px-6 py-4 border-b border-[var(--border-subtle)]">
            <div className="flex items-center gap-3">
              <h3 className="text-[14px] font-semibold tracking-tight">Plan Issue</h3>
              <span className="text-[var(--border)] text-xs">/</span>
              <PlannerWorkspacePicker
                workspaceId={effectiveWsId}
                onChange={(id) => {
                  setPlannerWsId(id)
                  setWsError(null)
                  planning.startNew()
                }}
              />
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--text-dim)] hover:bg-[var(--surface-hover)] transition-colors"
            >
              <X size={14} />
            </button>
          </div>

          {/* Chat area */}
          <div ref={chatRef} className="flex-1 overflow-y-auto px-6 py-4 min-h-[200px]">
            {/* Loading state */}
            {planning.loadingSession && (
              <div className="flex flex-col items-center justify-center py-16">
                <Spinner size={20} />
                <p className="mt-3 text-[11px] text-[var(--text-muted)] font-mono">Loading session{'\u2026'}</p>
              </div>
            )}

            {/* Empty state */}
            {planning.messages.length === 0 && !planning.generating && !planning.loadingSession && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <div className="w-10 h-10 rounded-xl bg-[var(--accent-dim)] flex items-center justify-center mb-4">
                  <Brain size={18} className="text-[var(--accent)]" />
                </div>
                <p className="text-[12px] text-[var(--text-dim)] mb-1 font-medium">Plan an implementation</p>
                <p className="text-[10px] text-[var(--text-muted)] max-w-[300px]">
                  Describe a feature or bug fix and Claude will analyze the codebase to create an implementation plan.
                </p>
              </div>
            )}

            {/* Messages */}
            {planning.messages.map((m, i) => (
              m.role === 'user' ? (
                <div key={`${planning.sessionId}-${i}`} className="flex justify-end my-3">
                  <div className="max-w-[85%] bg-[var(--accent-dim)] border border-[var(--accent-border)] rounded-xl rounded-br-sm px-4 py-3 text-[11px] whitespace-pre-wrap font-mono text-[var(--text)] leading-relaxed">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div
                  key={`${planning.sessionId}-${i}`}
                  className="my-3 bg-[var(--bg)] border border-[var(--border-subtle)] rounded-xl overflow-hidden"
                >
                  <div
                    className="p-5 text-[11px] leading-relaxed prose-planner"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                  />
                  <div className="px-5 pb-4">
                    <PlanIssueAction messageIndex={i} planning={planning} />
                  </div>
                </div>
              )
            ))}

            {/* Activity feed — streaming events */}
            {(planning.generating || planning.streamEvents?.length > 0) && (
              <ActivityFeed
                events={planning.streamEvents || []}
                isGenerating={planning.generating}
              />
            )}

            {/* Live draft */}
            {planning.generating && planning.streamEvents && (
              <LiveDraft events={planning.streamEvents} />
            )}

            {/* Issue creation progress */}
            {planning.creatingIssue != null && (
              <div className="flex items-center gap-2.5 py-3 px-4 my-2 rounded-lg bg-[var(--surface)] border border-[var(--border-subtle)]">
                <Spinner size={12} />
                <span className="text-[11px] text-[var(--text-muted)] font-mono">{'Creating GitHub issue\u2026'}</span>
              </div>
            )}
          </div>

          {/* Input area */}
          <div className="px-6 pb-5 pt-3 border-t border-[var(--border-subtle)]">
            <div className="relative">
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
                className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-xl p-3.5 pr-24 text-[11px] font-mono text-[var(--text)] resize-none focus:outline-none focus:border-[var(--accent-border)] disabled:opacity-40 placeholder:text-[var(--text-muted)] transition-colors"
                rows={2}
              />
              <div className="absolute right-2 bottom-2 flex items-center gap-1.5">
                {planning.generating ? (
                  <Button size="sm" onClick={() => planning.cancelGeneration()}>
                    Cancel
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={handleSend}
                    disabled={!inputValue.trim()}
                  >
                    {planning.hasPlan ? 'Refine' : 'Plan'}
                  </Button>
                )}
              </div>
            </div>
            {wsError && (
              <p className="mt-1.5 text-[10px] text-[var(--red)]">{wsError}</p>
            )}
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-[9px] text-[var(--text-muted)]">
                {(navigator.userAgentData?.platform || navigator.userAgent)?.toLowerCase().includes('mac') ? '\u2318' : 'Ctrl'}+Enter to send
              </span>
              {planning.hasPlan && !planning.generating && (
                <>
                  <span className="text-[var(--border)] text-[9px]">{'\u00b7'}</span>
                  <span className="text-[9px] text-[var(--text-muted)]">
                    Each plan above has its own "Create Issue" button
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
