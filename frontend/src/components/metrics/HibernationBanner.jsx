import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { PauseCircle, RefreshCw, Loader2 } from 'lucide-react'
import { checkRateLimit } from '../../api/client'

function formatSince(iso) {
  if (!iso) return null
  const then = new Date(iso)
  if (isNaN(then.getTime())) return null
  const secs = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000))
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ${mins % 60}m`
}

export function HibernationBanner({ hibernation }) {
  const queryClient = useQueryClient()
  const [feedback, setFeedback] = useState(null)

  const probe = useMutation({
    mutationFn: checkRateLimit,
    onMutate: () => setFeedback(null),
    onSuccess: (res) => {
      // Refresh metrics so the banner clears immediately if the swarm woke.
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      if (res?.woke || res?.available) {
        setFeedback({ tone: 'ok', text: 'Limit cleared — resuming' })
      } else {
        setFeedback({ tone: 'wait', text: 'Still rate-limited' })
      }
    },
    onError: (err) => setFeedback({ tone: 'err', text: err?.message || 'Probe failed' }),
  })

  // Hooks must run unconditionally; bail on render only after they're declared.
  if (!hibernation?.hibernating) return null

  const since = formatSince(hibernation.since)
  const feedbackColor =
    feedback?.tone === 'ok' ? 'var(--green)' : feedback?.tone === 'err' ? 'var(--red)' : 'var(--yellow)'

  return (
    <div
      className="relative overflow-hidden border-b border-[rgba(251,191,36,0.18)] animate-fade-in"
      style={{
        background:
          'linear-gradient(90deg, rgba(251,191,36,0.10) 0%, rgba(251,191,36,0.04) 28%, rgba(9,9,11,0) 65%), var(--bg-raised)',
      }}
    >
      {/* left accent stripe */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[2.5px]"
        style={{ background: 'var(--yellow)', boxShadow: '0 0 12px rgba(251,191,36,0.6)' }}
      />
      {/* slow light sweep along the bottom edge — "actively waiting" */}
      <div className="absolute bottom-0 left-0 right-0 h-px overflow-hidden">
        <div
          className="h-full w-1/3 animate-hib-sweep"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(251,191,36,0.7), transparent)' }}
        />
      </div>

      <div className="flex items-center gap-3.5 px-6 py-3">
        {/* pulsing icon chip */}
        <div className="relative shrink-0">
          <span
            className="absolute inset-0 rounded-lg"
            style={{ background: 'var(--yellow)', opacity: 0.15, animation: 'pulse-glow 2s ease-in-out infinite' }}
          />
          <div className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-[rgba(251,191,36,0.3)] bg-[var(--yellow-dim)]">
            <PauseCircle size={18} className="text-[var(--yellow)]" strokeWidth={2} />
          </div>
        </div>

        {/* message */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold tracking-tight text-[var(--text)]">
              Swarm hibernating
            </span>
            <span className="rounded border border-[rgba(251,191,36,0.3)] bg-[var(--yellow-dim)] px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--yellow)]">
              Rate limit
            </span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-[var(--text-dim)]">
            All agents paused &middot; auto-resumes when the limit clears
            {since ? <span className="text-[var(--text-muted)]"> &middot; for {since}</span> : null}
            {hibernation.reason ? (
              <span className="text-[var(--text-muted)]"> &middot; {hibernation.reason}</span>
            ) : null}
          </div>
        </div>

        {/* manual probe */}
        <div className="flex shrink-0 items-center gap-3">
          {feedback ? (
            <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: feedbackColor }}>
              {feedback.text}
            </span>
          ) : null}
          <button
            onClick={() => probe.mutate()}
            disabled={probe.isPending}
            className="group inline-flex items-center gap-1.5 rounded-md border border-[rgba(251,191,36,0.35)] bg-[var(--yellow-dim)] px-3 py-1.5 text-[11px] font-semibold text-[var(--yellow)] transition-all hover:bg-[rgba(251,191,36,0.2)] hover:border-[rgba(251,191,36,0.55)] disabled:cursor-not-allowed disabled:opacity-50"
            title="Probe Claude now instead of waiting for the next automatic check"
          >
            {probe.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <RefreshCw size={12} className="transition-transform group-hover:rotate-90" />
            )}
            {probe.isPending ? 'Checking…' : 'Check rate limit'}
          </button>
        </div>
      </div>
    </div>
  )
}
