const VARIANTS = {
  green: 'bg-[rgba(0,184,148,0.15)] text-[var(--green)] border-[rgba(0,184,148,0.3)]',
  blue: 'bg-[rgba(116,185,255,0.15)] text-[var(--blue)] border-[rgba(116,185,255,0.3)]',
  yellow: 'bg-[rgba(253,203,110,0.15)] text-[var(--yellow)] border-[rgba(253,203,110,0.3)]',
  red: 'bg-[rgba(225,112,85,0.15)] text-[var(--red)] border-[rgba(225,112,85,0.3)]',
  purple: 'bg-[rgba(108,92,231,0.15)] text-[var(--accent)] border-[rgba(108,92,231,0.3)]',
  dim: 'bg-[rgba(139,143,163,0.1)] text-[var(--text-dim)] border-[rgba(139,143,163,0.2)]',
}

export function Badge({ variant = 'dim', children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${VARIANTS[variant] || VARIANTS.dim} ${className}`}
    >
      {children}
    </span>
  )
}
