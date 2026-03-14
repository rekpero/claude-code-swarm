export function MetricCard({ label, value, color }) {
  const colorMap = {
    green: 'var(--green)',
    blue: 'var(--blue)',
    yellow: 'var(--yellow)',
    red: 'var(--red)',
    accent: 'var(--accent)',
    text: 'var(--text)',
  }
  const c = colorMap[color] || 'var(--text)'

  return (
    <div className="flex flex-col p-4 bg-[var(--surface)] border border-[var(--border)] rounded-lg relative overflow-hidden">
      <div
        className="absolute top-0 left-0 right-0 h-0.5"
        style={{ background: c }}
      />
      <span
        className="text-3xl font-bold tabular-nums leading-none mb-1"
        style={{ color: c }}
      >
        {value ?? '—'}
      </span>
      <span className="text-[11px] font-medium text-[var(--text-dim)] uppercase tracking-wide">
        {label}
      </span>
    </div>
  )
}
