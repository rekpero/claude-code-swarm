const TABS = [
  { id: 'agents', label: 'Agents' },
  { id: 'issues', label: 'Issues' },
  { id: 'prs', label: 'PRs' },
]

export function TabNav({ activeTab, onTabChange, counts = {} }) {
  return (
    <div className="flex gap-1 px-5 border-b border-[var(--border)] bg-[var(--surface)]">
      {TABS.map((tab) => {
        const count = counts[tab.id]
        const isActive = activeTab === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
              isActive
                ? 'border-[var(--accent)] text-[var(--text)]'
                : 'border-transparent text-[var(--text-dim)] hover:text-[var(--text)]'
            }`}
          >
            {tab.label}
            {count != null && count > 0 && (
              <span
                className={`ml-1.5 px-1.5 py-0.5 rounded text-[10px] ${
                  isActive
                    ? 'bg-[rgba(108,92,231,0.2)] text-[var(--accent)]'
                    : 'bg-[var(--border)] text-[var(--text-dim)]'
                }`}
              >
                {count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
