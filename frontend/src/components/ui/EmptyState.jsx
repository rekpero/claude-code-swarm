export function EmptyState({ icon: Icon, message, description }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {Icon && (
        <div className="mb-4 p-3 rounded-xl bg-[var(--accent-dim)]">
          <Icon size={24} strokeWidth={1.5} className="text-[var(--text-muted)]" />
        </div>
      )}
      <p className="text-[var(--text-dim)] text-sm font-medium">{message}</p>
      {description && (
        <p className="text-[var(--text-muted)] text-xs mt-1.5 max-w-[280px]">{description}</p>
      )}
    </div>
  )
}
