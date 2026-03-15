export function Card({ children, className = '', glow = false, ...props }) {
  return (
    <div
      className={`rounded-lg border bg-[var(--surface)] border-[var(--border)] ${glow ? 'glow-border' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className = '' }) {
  return (
    <div className={`px-4 py-3 border-b border-[var(--border-subtle)] ${className}`}>
      {children}
    </div>
  )
}

export function CardBody({ children, className = '' }) {
  return <div className={`p-4 ${className}`}>{children}</div>
}
