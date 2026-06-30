import { useState, useRef, useEffect } from 'react'
import { Pause, Play, ChevronDown, Loader2 } from 'lucide-react'
import { useWorkspaces, usePauseWorkspace, useResumeWorkspace } from '../../hooks/useWorkspaces'

const DURATIONS = [
  { label: '15 minutes', minutes: 15 },
  { label: '1 hour', minutes: 60 },
  { label: '3 hours', minutes: 180 },
  { label: 'Until I resume', minutes: null },
]

// Backend stores naive UTC timestamps (no 'Z'); JS would otherwise read them as
// local time. Force UTC so the countdown is accurate.
function parseUtc(s) {
  if (!s) return null
  const isUtc = s.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(s)
  return new Date(isUtc ? s : `${s}Z`)
}

// A paused_until far in the future means "indefinite" (the 9999 sentinel).
function isIndefinite(date) {
  return date && date.getUTCFullYear() >= 9999
}

function formatRemaining(ms) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m left`
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')} left`
}

export function PauseControl({ wsId }) {
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const ref = useRef(null)
  const { data } = useWorkspaces()
  const pause = usePauseWorkspace()
  const resume = useResumeWorkspace()

  const workspace = data?.workspaces?.find((w) => w.id === wsId)
  const pausedUntil = parseUtc(workspace?.paused_until)
  const indefinite = isIndefinite(pausedUntil)
  const paused = !!pausedUntil && (indefinite || pausedUntil.getTime() > now)

  // Tick once a second while paused so the countdown stays live and the pill
  // flips back automatically when the timer elapses.
  useEffect(() => {
    if (!paused || indefinite) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [paused, indefinite])

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  if (!wsId) return null

  const handlePause = (minutes) => {
    setOpen(false)
    pause.mutate({ id: wsId, minutes })
  }

  if (paused) {
    return (
      <div className="flex items-center gap-1.5">
        <span
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium text-[var(--yellow)] bg-[rgba(234,179,8,0.08)] border border-[rgba(234,179,8,0.15)]"
          title="Automation is paused for this workspace"
        >
          <Pause size={9} className="fill-current" />
          {indefinite ? 'Paused' : `Paused · ${formatRemaining(pausedUntil.getTime() - now)}`}
        </span>
        <button
          onClick={() => resume.mutate(wsId)}
          disabled={resume.isPending}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-[var(--text-dim)] border border-[var(--border)] hover:text-[var(--text)] hover:border-[var(--text-muted)] hover:bg-[var(--surface-hover)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          title="Resume automation now"
        >
          {resume.isPending ? <Loader2 size={9} className="animate-spin" /> : <Play size={9} className="fill-current" />}
          Resume
        </button>
      </div>
    )
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={pause.isPending}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-[var(--text-muted)] border border-[var(--border)] hover:text-[var(--text-dim)] hover:border-[var(--text-muted)] hover:bg-[var(--surface-hover)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        title="Pause automation for this workspace"
      >
        {pause.isPending ? <Loader2 size={9} className="animate-spin" /> : <Pause size={9} />}
        Pause
        <ChevronDown size={9} className="text-[var(--text-muted)]" />
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-[0_12px_40px_rgba(0,0,0,0.6)] min-w-[180px] z-50 overflow-hidden animate-fade-in">
          <div className="px-3 pt-2.5 pb-1.5 text-[9px] uppercase tracking-wider text-[var(--text-muted)] font-semibold">
            Pause automation for
          </div>
          {DURATIONS.map((d) => (
            <div
              key={d.label}
              onClick={() => handlePause(d.minutes)}
              className="flex items-center gap-2 px-3 py-2 cursor-pointer text-[11px] hover:bg-[var(--surface-hover)] transition-colors"
            >
              <span className="flex-1 font-medium">{d.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
