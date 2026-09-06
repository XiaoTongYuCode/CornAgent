import { getToolApprovalDisplay } from './toolApprovalDisplay'
import type {
  MessageRenderContentPart,
  MessageRenderGroupItem,
} from './utils/messageRenderPlan'
import { resolveAgentReasoningPartTitle } from './utils/agentReasoningTitle'

function normalizeTitleValue(value?: string | null): string {
  return value?.trim() ?? ''
}

export function isStreamingTitle(title?: string | null): boolean {
  return title?.trim().includes('正在') === true
}

export function getToolCallDisplayTitle(part: MessageRenderContentPart): string {
  if (part.metadata?.subagent === true) {
    const active = ['queued', 'running'].includes(String(part.metadata.status))
    return `${active ? '正在' : '已'}执行子任务：${part.title ?? ''}`
  }
  const controlTitles: Record<string, string> = {
    spawn_subagents: '已下派子任务', list_subagents: '已读取子任务状态',
    collect_subagent_results: '已汇集子任务结果', delegate_tasks: '已并行下派任务',
    wait_subagents: '已等待子任务',
  }
  const control = controlTitles[String(part.metadata?.tool_name)]
  if (control && part.metadata?.status === 'failed') return '子任务操作失败'
  if (control && part.metadata?.status === 'cancelled') return '已取消'
  if (control) return part.metadata?.status === 'waiting' ? '正在等待子任务' : control
  const partTitle = normalizeTitleValue(part.title) || '工具调用'
  const approvalDisplay = getToolApprovalDisplay(part.metadata)
  return approvalDisplay?.title ?? partTitle
}

export function resolveToolCallDisplayTitle(
  part: MessageRenderContentPart,
  isActive: boolean,
): string {
  const title = getToolCallDisplayTitle(part)
  if (isActive || !title.startsWith('正在')) {
    return title
  }
  return `已${title.slice(2)}`
}

export function getActiveToolCallPartId(
  parts: MessageRenderContentPart[],
  isProcessActive: boolean,
): string | null {
  const tail = parts[parts.length - 1]
  return tail && isStreamingToolCallPart(tail, isProcessActive) ? tail.id : null
}

export interface CompanyEntityLookupDisplay {
  content: string
  failed: boolean
  title: string
}

export function getCompanyEntityLookupDisplay(
  part: MessageRenderContentPart,
): CompanyEntityLookupDisplay | null {
  if (part.metadata?.tool_name !== 'select_company_entity') {
    return null
  }
  const lookupStatus = typeof part.metadata.lookup_status === 'string'
    ? part.metadata.lookup_status.trim()
    : ''
  const candidateCount = typeof part.metadata.candidate_count === 'number'
    ? part.metadata.candidate_count
    : 0
  const selectedCount = typeof part.metadata.selected_count === 'number'
    ? part.metadata.selected_count
    : 0
  const selectionState = typeof part.metadata.selection_state === 'string'
    ? part.metadata.selection_state.trim()
    : ''
  const candidateSource = typeof part.metadata.candidate_source === 'string'
    ? part.metadata.candidate_source.trim()
    : ''
  if (
    selectionState === 'selected' ||
    (selectionState === 'partial' && selectedCount > 0)
  ) {
    return {
      content: '',
      failed: false,
      title: '已选择公司实体',
    }
  }
  if (lookupStatus === 'unavailable') {
    return {
      content: '公司查询暂不可用，请重试。',
      failed: true,
      title: '公司查询暂不可用，请重试',
    }
  }
  if (lookupStatus === 'degraded') {
    let message = '公司查询尚未完成，请重试'
    if (candidateCount > 0) {
      if (candidateSource === 'company_provider') {
        message = '已使用企业信息源查询'
      } else if (candidateSource === 'company_profile') {
        message = '已使用内部企业主档查询'
      } else if (candidateSource === 'company_index') {
        message = '已使用公司档案查询'
      } else {
        message = '已查询公司实体'
      }
    }
    return {
      content: `${message}。`,
      failed: false,
      title: message,
    }
  }
  return null
}

export function isFailedToolCallPart(
  part: MessageRenderContentPart,
  displayTitle = getToolCallDisplayTitle(part),
): boolean {
  const approvalDisplay = getToolApprovalDisplay(part.metadata)
  const companyLookupDisplay = getCompanyEntityLookupDisplay(part)
  return (
    part.metadata?.failed === true ||
    companyLookupDisplay?.failed === true ||
    approvalDisplay?.status === 'denied' ||
    displayTitle.includes('失败')
  )
}

export function isStreamingToolCallPart(
  part: MessageRenderContentPart,
  isProcessActive: boolean,
): boolean {
  return (
    part.kind === 'tool_call' &&
    isProcessActive &&
    !isFailedToolCallPart(part) &&
    (part.metadata?.status === 'running' || part.metadata?.status === 'waiting' || isStreamingTitle(getToolCallDisplayTitle(part)))
  )
}

export function getLastStreamingToolCallTitleInGroup(
  item: MessageRenderGroupItem,
  parts: MessageRenderContentPart[],
  isProcessActive: boolean,
): string | null {
  const tailIndex = item.indexes[item.indexes.length - 1]
  const tail = typeof tailIndex === 'number' ? parts[tailIndex] : null
  return tail && isStreamingToolCallPart(tail, isProcessActive)
    ? getToolCallDisplayTitle(tail)
    : null
}

export function getStreamingGroupTitleInGroup(
  item: MessageRenderGroupItem,
  parts: MessageRenderContentPart[],
  isProcessActive: boolean,
): string | null {
  if (!isProcessActive) {
    return null
  }

  const lastPartIndex = item.indexes[item.indexes.length - 1]
  const lastPart = typeof lastPartIndex === 'number' ? parts[lastPartIndex] : null
  if (lastPart?.kind === 'reasoning') {
    return resolveAgentReasoningPartTitle(lastPart.title, true)
  }

  return getLastStreamingToolCallTitleInGroup(item, parts, true)
}

export function hasFollowingContentAfterGroup(
  item: MessageRenderGroupItem,
  parts: MessageRenderContentPart[],
  allParts: MessageRenderContentPart[] = parts,
): boolean {
  const lastPartIndex = item.indexes[item.indexes.length - 1]
  const lastPart = typeof lastPartIndex === 'number' ? parts[lastPartIndex] : null
  if (!lastPart) {
    return false
  }

  const position = allParts.findIndex((part) => part.id === lastPart.id)
  return position >= 0 && position < allParts.length - 1
}

interface CollapsibleGroupTitleState {
  hasFollowingContent: boolean
  isProcessActive: boolean
}

export function resolveCollapsibleGroupTitle(
  item: MessageRenderGroupItem,
  parts: MessageRenderContentPart[],
  state: CollapsibleGroupTitleState,
): string {
  if (!state.isProcessActive || state.hasFollowingContent) {
    return item.title
  }

  return getStreamingGroupTitleInGroup(item, parts, true) ?? item.title
}
