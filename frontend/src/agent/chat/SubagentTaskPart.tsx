import { theme } from 'antd'
import { Component, RotateCwSquare } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/catalog'
import { subagentMetadata } from '../types'
import { CollapsibleContent } from './CollapsibleContent'
import type { AgentChatMessageContentPart } from './types'
import { getSubagentIconColor } from './utils/subagentIconColor'
export const SUBAGENT_CONTROL_KEYS = {
  spawn_subagents: 'subagentSpawned', list_subagents: 'subagentList',
  collect_subagent_results: 'subagentCollect', wait_subagents: 'subagentWaited',
  delegate_tasks: 'subagentDelegate',
} satisfies Record<string, MessageKey>

interface Props {
  part: AgentChatMessageContentPart
  open: boolean
  setOpen: (open: boolean) => void
}

export function SubagentTaskPart({ part, open, setOpen }: Props) {
  const { token } = theme.useToken()
  const task = subagentMetadata(part)
  if (!task) return null
  const failed = task.status === 'failed' || task.status === 'timed_out'
  const color = getSubagentIconColor(task.task_id, token.colorBgContainer)
  return (
    <div className="chat-subagent-task" data-task-id={task.task_id} data-status={task.status}>
      <CollapsibleContent
        title={<span>{task.title}</span>}
        titleIcon={Component}
        titleIconColor={color}
        titleClassName={failed ? 'chat-markdown-message-content__tool-title--failed' : ''}
        className="chat-markdown-message-content__tool"
        bodyClassName="chat-markdown-message-content__tool-body"
        content={part.content}
        streaming={false}
        open={open}
        onOpen={() => setOpen(true)}
        onClose={() => setOpen(false)}
        scrollable
      />
    </div>
  )
}

export function SubagentControlPart({ part, open, setOpen }: Props) {
  const { t } = useI18n()
  const name = String(part.metadata?.tool_name) as keyof typeof SUBAGENT_CONTROL_KEYS
  const key = SUBAGENT_CONTROL_KEYS[name]
  if (!key) return null
  const waiting = part.metadata?.status === 'waiting'
  const cancelled = part.metadata?.status === 'cancelled'
  const failed = part.metadata?.status === 'failed'
  const count = Number(part.metadata?.task_count ?? 0)
  const content = part.content || (part.metadata?.timed_out === true ? t('subagentWaitTimeout') : '')
  return (
    <CollapsibleContent
      title={`${t(failed ? 'subagentOperationFailed' : cancelled ? 'subagentCancelled' : waiting ? 'subagentWaiting' : key)} · ${t('subagentTaskCount', { count })}`}
      titleIcon={waiting || name === 'wait_subagents' ? RotateCwSquare : Component}
      titleStreaming={waiting}
      titleTransition
      content={content}
      open={open}
      onOpen={() => setOpen(true)}
      onClose={() => setOpen(false)}
      scrollable
    />
  )
}
