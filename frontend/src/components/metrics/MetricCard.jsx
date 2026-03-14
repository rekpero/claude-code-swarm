export function MetricCard({ label, value, color }) {
  const colorMap = {
    green: 'var(--green)',
    blue: 'var(--blue)',
    yellow: 'var(--yellow)',
    red: 'var(--red)',
    accent: 'var(--accent)',
    text: 'var(--text)',
  }
  const dimMap = {
    green: 'var(--green-dim)',
    blue: 'var(--blue-dim)',
    yellow: 'var(--yellow-dim)',
    red: 'var(--red-dim)',
    accent: 'var(--accent-dim)',
    text: 'rgba(220,223,232,0.04)',
  }
  const c = colorMap[color] || 'var(--text)'
  const bg = dimMap[color] || 'rgba(220,223,232,0.04)'

  return (
    <div className="flex flex-col px-4 py-3.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg relative overflow-hidden group hover:border-[var(--text-muted)] transition-all">
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{ background: `radial-gradient(circle at 50% 0%, ${bg}, transparent 70%)` }}
      />
      <span
        className="relative text-2xl font-bold tabular-nums leading-none mb-1.5 font-mono"
        style={{ color: c }}
      >
        {value ?? '\u2014'}
      </span>
      <span className="relative text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-widest">
        {label}
      </span>
    </div>
  )
}
