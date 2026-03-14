import { Loader2 } from 'lucide-react'

const VARIANTS = {
  primary: 'bg-[var(--accent)] border-transparent text-white hover:brightness-110 shadow-[0_0_12px_rgba(139,92,246,0.15)]',
  ghost: 'bg-transparent border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] hover:border-[var(--text-muted)]',
  danger: 'bg-[var(--red-dim)] border-transparent text-[var(--red)] hover:bg-[rgba(248,113,113,0.2)]',
}

export function Button({
  as: Component = 'button',
  variant = 'ghost',
  size = 'md',
  loading = false,
  disabled = false,
  children,
  className = '',
  ...props
}) {
  const sizeClass = size === 'sm' ? 'px-2.5 py-1 text-[11px]' : 'px-4 py-2 text-[12px]'
  const extraProps = Component === 'button' ? { disabled: disabled || loading } : {}
  return (
    <Component
      className={`inline-flex items-center justify-center gap-1.5 border rounded-md font-medium transition-all duration-150 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${sizeClass} ${VARIANTS[variant] || VARIANTS.ghost} ${className}`}
      {...extraProps}
      {...props}
    >
      {loading && <Loader2 size={11} className="animate-spin" />}
      {children}
    </Component>
  )
}
