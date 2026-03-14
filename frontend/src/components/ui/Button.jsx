import { Loader2 } from 'lucide-react'

const VARIANTS = {
  primary: 'bg-[var(--accent)] border-[var(--accent)] text-white hover:opacity-90',
  ghost: 'bg-transparent border-[var(--border)] text-[var(--text)] hover:bg-white/5',
  danger: 'bg-[var(--red)] border-[var(--red)] text-white hover:opacity-90',
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
  const sizeClass = size === 'sm' ? 'px-3 py-1 text-[11px]' : 'px-4 py-2 text-[12px]'
  const extraProps = Component === 'button' ? { disabled: disabled || loading } : {}
  return (
    <Component
      className={`inline-flex items-center gap-2 border rounded-md font-medium transition-all duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${sizeClass} ${VARIANTS[variant] || VARIANTS.ghost} ${className}`}
      {...extraProps}
      {...props}
    >
      {loading && <Loader2 size={12} className="animate-spin" />}
      {children}
    </Component>
  )
}
