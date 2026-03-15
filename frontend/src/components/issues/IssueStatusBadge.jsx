import { Badge } from '../ui/Badge'

const STATUS_MAP = {
  resolved: { variant: 'green', label: 'Resolved' },
  in_progress: { variant: 'purple', label: 'In Progress' },
  pending: { variant: 'yellow', label: 'Pending' },
  needs_human: { variant: 'red', label: 'Needs Human' },
  pr_created: { variant: 'blue', label: 'PR Created' },
}

export function IssueStatusBadge({ status }) {
  const { variant, label } = STATUS_MAP[status] || { variant: 'dim', label: status }
  return <Badge variant={variant}>{label}</Badge>
}
