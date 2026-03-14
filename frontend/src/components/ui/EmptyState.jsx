export function EmptyState({ icon: Icon, message, description }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      {Icon && (
        <div className="mb-3 text-[var(--text-dim)]">
          <Icon size={32} strokeWidth={1} />
        </div>
      )}
      <p className="text-[var(--text-dim)] text-sm">{message}</p>
      {description && (
        <p className="text-[var(--text-dim)] text-xs mt-1 opacity-70">{description}</p>
      )}
    </div>
  )
}
