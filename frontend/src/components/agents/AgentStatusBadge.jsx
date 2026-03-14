import { Badge } from '../ui/Badge'

const STATUS_MAP = {
  running: { variant: 'purple', label: 'Running' },
  completed: { variant: 'green', label: 'Completed' },
  failed: { variant: 'red', label: 'Failed' },
  rate_limited: { variant: 'yellow', label: 'Rate Limited' },
  timed_out: { variant: 'red', label: 'Timed Out' },
}

export function AgentStatusBadge({ status }) {
  const { variant, label } = STATUS_MAP[status] || { variant: 'dim', label: status }
  return <Badge variant={variant}>{label}</Badge>
}
