const VARIANTS = {
  green: 'bg-[var(--green-dim)] text-[var(--green)] border-transparent',
  blue: 'bg-[var(--blue-dim)] text-[var(--blue)] border-transparent',
  yellow: 'bg-[var(--yellow-dim)] text-[var(--yellow)] border-transparent',
  red: 'bg-[var(--red-dim)] text-[var(--red)] border-transparent',
  purple: 'bg-[var(--accent-dim)] text-[var(--accent)] border-transparent',
  dim: 'bg-[rgba(92,95,115,0.08)] text-[var(--text-dim)] border-transparent',
}

export function Badge({ variant = 'dim', children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wide uppercase whitespace-nowrap border ${VARIANTS[variant] || VARIANTS.dim} ${className}`}
    >
      {children}
    </span>
  )
}
