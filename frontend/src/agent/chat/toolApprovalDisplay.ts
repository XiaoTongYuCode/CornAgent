interface ToolApprovalPresentation {
  denied: {
    fallbackContent: string
    title: string
  }
  reviewing: {
    fallbackContent: string
    fallbackTitle: string
  }
}

const TOOL_APPROVAL_PRESENTATION: ToolApprovalPresentation = {
  reviewing: {
    fallbackTitle: '自动审核中',
    fallbackContent: '正在审查此请求',
  },
  denied: {
    title: '自动审批拒绝',
    fallbackContent: '自动审批判定请求不应执行。',
  },
}

export interface ToolApprovalDisplay {
  content: string
  status: 'reviewing' | 'denied'
  title: string
}

function stringFromMetadata(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function getToolApprovalDisplay(
  metadata: Record<string, unknown> | null | undefined,
): ToolApprovalDisplay | null {
  const approval = metadata?.approval
  if (!approval || typeof approval !== 'object' || Array.isArray(approval)) {
    return null
  }

  const approvalMetadata = approval as Record<string, unknown>
  const status = stringFromMetadata(approvalMetadata.status)

  if (status === 'reviewing') {
    return {
      status,
      title:
        stringFromMetadata(approvalMetadata.title) ??
        TOOL_APPROVAL_PRESENTATION.reviewing.fallbackTitle,
      content:
        stringFromMetadata(approvalMetadata.description) ??
        TOOL_APPROVAL_PRESENTATION.reviewing.fallbackContent,
    }
  }

  if (status === 'denied') {
    return {
      status,
      title: TOOL_APPROVAL_PRESENTATION.denied.title,
      content:
        stringFromMetadata(approvalMetadata.rationale) ??
        TOOL_APPROVAL_PRESENTATION.denied.fallbackContent,
    }
  }

  return null
}
