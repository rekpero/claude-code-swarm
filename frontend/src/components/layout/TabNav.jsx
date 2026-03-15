const TABS = [
  { id: 'agents', label: 'Agents' },
  { id: 'issues', label: 'Issues' },
  { id: 'prs', label: 'PRs' },
]

export function TabNav({ activeTab, onTabChange, counts = {} }) {
  return (
    <div className="flex gap-0 px-6 border-b border-[var(--border)] bg-[var(--bg)]">
      {TABS.map((tab) => {
        const count = counts[tab.id]
        const isActive = activeTab === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`relative px-5 py-2.5 text-[12px] font-medium transition-colors ${
              isActive
                ? 'text-[var(--text)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-dim)]'
            }`}
          >
            {tab.label}
            {count != null && count > 0 && (
              <span
                className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold ${
                  isActive
                    ? 'bg-[var(--accent-dim)] text-[var(--accent)]'
                    : 'text-[var(--text-muted)]'
                }`}
              >
                {count}
              </span>
            )}
            {isActive && (
              <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-[var(--accent)] rounded-t-full shadow-[0_0_8px_var(--accent-glow)]" />
            )}
          </button>
        )
      })}
    </div>
  )
}
