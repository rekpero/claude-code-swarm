import { useState, useEffect } from 'react'
import { Bot, ChevronLeft, ChevronRight } from 'lucide-react'
import { AgentCard } from './AgentCard'
import { EmptyState } from '../ui/EmptyState'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useAgents } from '../../hooks/useAgents'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

const PAGE_SIZE = 20

export function ActiveAgents() {
  const [offset, setOffset] = useState(0)
  const { selectedWorkspaceId } = useWorkspaceContext()

  useEffect(() => { setOffset(0) }, [selectedWorkspaceId])
  const { data, isLoading } = useAgents(selectedWorkspaceId, { limit: PAGE_SIZE, offset })

  const agents = data?.agents || []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  return (
    <div className="px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">
          Active Agents
          {total > 0 && <span className="ml-2 text-[var(--text-dim)] font-normal text-xs">({total})</span>}
        </h2>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
            >
              <ChevronLeft size={12} />
            </Button>
            <span className="text-[11px] text-[var(--text-dim)]">
              {currentPage} / {totalPages}
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((v) => v + PAGE_SIZE)}
            >
              <ChevronRight size={12} />
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : agents.length === 0 ? (
        <EmptyState icon={Bot} message="No agents running" description="Agents will appear here when issues are dispatched" />
      ) : (
        <div className="flex flex-col gap-2">
          {agents.map((agent) => (
            <AgentCard key={agent.agent_id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  )
}
