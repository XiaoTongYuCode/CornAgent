import { describe, expect, it } from 'vitest'

import type { AgentChatMessageContentPart } from './types'
import { projectAgentMessageSections } from './projectAgentMessageSections'

function part(
  id: string,
  kind: AgentChatMessageContentPart['kind'],
  content = '',
  metadata: AgentChatMessageContentPart['metadata'] = null,
): AgentChatMessageContentPart {
  return { id, kind, content, metadata }
}

describe('projectAgentMessageSections', () => {
  it('keeps a multiline body whole and omits the process group', () => {
    const markdown = part('answer-1', 'markdown', '第一段。\n\n第二段。')

    expect(projectAgentMessageSections([markdown])).toEqual({
      hasProcessActivity: false,
      normalizedParts: [markdown],
      processParts: [],
      visibleBoundaryId: null,
      visibleParts: [markdown],
    })
  })

  it('folds every prior narrative and tool behind the latest body', () => {
    const parts = [
      part('body-1', 'markdown', '先检查工作区。'),
      part('tool-1', 'tool_call', '找到 0 条记录。'),
      part('body-2', 'markdown', '再核对字段。'),
      part('tool-2', 'tool_call', '找到 2 个字段。'),
      part('body-3', 'markdown', '公司已创建。'),
    ]
    const result = projectAgentMessageSections(parts)

    expect(result.processParts.map(({ id }) => id)).toEqual([
      'body-1', 'tool-1', 'body-2', 'tool-2',
    ])
    expect(result.visibleParts.map(({ id }) => id)).toEqual(['body-3'])
    expect(result.visibleBoundaryId).toBe('body-3')
  })

  it('keeps the pending question interactive outside the process group', () => {
    const result = projectAgentMessageSections([
      part('body-1', 'markdown', '需要确认范围。'),
      part('tool-1', 'tool_call', '已读取当前配置。'),
      part('question-1', 'user_question', '', { status: 'pending' }),
    ])

    expect(result.processParts).toEqual([])
    expect(result.visibleParts.map(({ id }) => id)).toEqual(['body-1', 'tool-1', 'question-1'])
  })

  it('folds a resolved question when a later body arrives', () => {
    const result = projectAgentMessageSections([
      part('question-1', 'user_question', '使用默认范围', { status: 'answered' }),
      part('body-1', 'markdown', '已按默认范围完成。'),
    ])

    expect(result.processParts.map(({ id }) => id)).toEqual(['question-1'])
    expect(result.visibleParts.map(({ id }) => id)).toEqual(['body-1'])
  })

  it('retains an empty running tool and supports process-only output', () => {
    const result = projectAgentMessageSections([
      part('reasoning-1', 'reasoning', '正在规划'),
      part('tool-1', 'tool_call'),
    ])

    expect(result.processParts.map(({ id }) => id)).toEqual(['reasoning-1', 'tool-1'])
    expect(result.visibleParts).toEqual([])
    expect(result.visibleBoundaryId).toBeNull()
  })

  it('keeps trailing activity outside until the next non-empty body arrives', () => {
    const parts = [
      part('tool-before', 'tool_call', '前置检查完成。'),
      part('body-1', 'markdown', '开始执行。\n\n稍后汇总。'),
      part('reasoning-after', 'reasoning', '核对结果'),
      part('tool-after', 'tool_call'),
      part('task-after', 'tool_call', '', { subagent: true, task_id: 'task-1' }),
      part('question-after', 'user_question', '继续', { status: 'answered' }),
      part('body-2', 'markdown', '  \n '),
    ]
    const initial = projectAgentMessageSections(parts)
    expect(initial.processParts.map(({ id }) => id)).toEqual(['tool-before'])
    expect(initial.visibleParts.map(({ id }) => id)).toEqual([
      'body-1', 'reasoning-after', 'tool-after', 'task-after', 'question-after',
    ])
    expect(initial.visibleBoundaryId).toBe('body-1')

    const next = [...parts.slice(0, -1), part('body-2', 'markdown', '执行完成。')]
    const result = projectAgentMessageSections(next)
    expect(result.processParts.map(({ id }) => id)).toEqual(parts.slice(0, -1).map(({ id }) => id))
    expect(result.visibleParts.map(({ id }) => id)).toEqual(['body-2'])
    expect(result.visibleBoundaryId).toBe('body-2')
    expect(projectAgentMessageSections(JSON.parse(JSON.stringify(next)))).toEqual(result)
  })

  it('never folds an unanswered question even when it precedes the latest body', () => {
    const result = projectAgentMessageSections([
      part('tool-before', 'tool_call'),
      part('question-before', 'user_question', '', { status: 'pending' }),
      part('body-1', 'markdown', '等待确认。'),
      part('tool-after', 'tool_call'),
    ])
    expect(result.processParts.map(({ id }) => id)).toEqual(['tool-before'])
    expect(result.visibleParts.map(({ id }) => id)).toEqual(['question-before', 'body-1', 'tool-after'])
  })
})
