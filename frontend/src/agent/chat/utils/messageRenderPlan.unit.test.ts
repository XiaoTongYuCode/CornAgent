import { createMessageRenderPlan, type MessageRenderContentPart } from './messageRenderPlan'

describe('Desktop reasoning and tool render groups', () => {
  it('groups adjacent reasoning and tool calls while keeping a question outside the group', () => {
    const parts: MessageRenderContentPart[] = [
      { id: 'reason-1', kind: 'reasoning', content: '先检查职位要求。' },
      { id: 'tool-1', kind: 'tool_call', content: '读取简历', metadata: { tool_name: 'read' } },
      { id: 'question-1', kind: 'user_question', content: '优先看哪位候选人？' },
      { id: 'reason-2', kind: 'reasoning', content: '根据回答继续。' },
    ]

    expect(createMessageRenderPlan(parts)).toEqual([
      expect.objectContaining({ id: 'group-reason-1', indexes: [0, 1], kind: 'group' }),
      { index: 2, kind: 'part' },
      expect.objectContaining({ id: 'group-reason-2', indexes: [3], kind: 'group' }),
    ])
  })

  it('switches long process runs to the grouped presentation', () => {
    const parts: MessageRenderContentPart[] = Array.from({ length: 4 }, (_, index) => ({
      id: `reason-${index + 1}`,
      kind: 'reasoning',
      content: `步骤 ${index + 1}`,
    }))

    expect(createMessageRenderPlan(parts)[0]).toEqual(expect.objectContaining({
      indexes: [0, 1, 2, 3],
      presentation: 'grouped',
    }))
  })
})

it('summarizes child tasks, orchestration and waits separately', () => {
  const parts: MessageRenderContentPart[] = [
    { id: 'spawn', kind: 'tool_call', content: '', metadata: { tool_name: 'spawn_subagents' } },
    { id: 'child-a', kind: 'tool_call', title: '自定义模型标题', content: '', metadata: { subagent: true } },
    { id: 'child-b', kind: 'tool_call', content: '', metadata: { subagent: true } },
    { id: 'wait', kind: 'tool_call', content: '', metadata: { tool_name: 'wait_subagents' } },
  ]
  const plan = createMessageRenderPlan(parts)
  expect(plan[0]).toEqual(expect.objectContaining({
    title: '已执行 2 个子任务 已编排子任务 1 次 已等待子任务 1 次',
  }))
})
