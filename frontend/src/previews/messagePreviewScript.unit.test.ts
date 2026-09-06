import { createPreviewScript, initialPreviewParts, readPreviewFrame, type PreviewMode } from './messagePreviewScript'
import { createMessageRenderPlan } from '../agent/chat/utils/messageRenderPlan'
import { projectDesktopContentParts } from '../agent/chat/projectDesktopContentParts'

it('shows running tools long enough to preview shimmer, then completes them without adding a body', () => {
  const steps = createPreviewScript('tools', 'demo', initialPreviewParts)
  expect(readPreviewFrame(steps, 2000).parts['zh-CN'].at(-1)?.title).toBe('正在读取示例资料')
  expect(readPreviewFrame(steps, 3500).parts['zh-CN'].at(-1)).toMatchObject({ id: 'demo-read', title: '已读取示例资料' })
  const secondTool = readPreviewFrame(steps, 5000)
  expect(secondTool.parts['zh-CN'].at(-2)?.title).toBe('已读取示例资料')
  expect(secondTool.parts['zh-CN'].at(-1)?.title).toBe('正在核对示例结果')
  const finished = readPreviewFrame(steps, 8100)
  expect(finished.done).toBe(true)
  expect(finished.parts['zh-CN'].at(-1)?.title).toBe('已核对示例结果')
  expect(finished.parts['zh-CN'].filter((part) => part.kind === 'markdown')).toHaveLength(1)
})

it('waits for the first token before reasoning and moves the final body boundary while streaming', () => {
  const steps = createPreviewScript('sequence', 'demo', initialPreviewParts)
  expect(readPreviewFrame(steps, 0).parts['zh-CN']).toEqual([])
  expect(readPreviewFrame(steps, 1600).parts['zh-CN'].map((part) => part.kind)).toEqual(['reasoning'])
  const beforeAnswer = steps.slice(0, -1).reduce((duration, step) => duration + step.duration, 0)
  expect(readPreviewFrame(steps, beforeAnswer - 1).parts['zh-CN'].at(-1)?.kind).toBe('tool_call')
  expect(readPreviewFrame(steps, beforeAnswer).parts['zh-CN'].at(-1)).toMatchObject({ id: 'demo-answer', kind: 'markdown', content: '新' })
  expect(readPreviewFrame(steps, beforeAnswer + 2800).done).toBe(true)
  expect(initialPreviewParts['zh-CN']).toHaveLength(5)
})

it('replays the first-token transition independently and reuses static frames', () => {
  const steps = createPreviewScript('first-token', 'token', initialPreviewParts)
  const waiting = readPreviewFrame(steps, 0)
  expect(waiting.parts['zh-CN']).toEqual([])
  expect(readPreviewFrame(steps, 1500).parts['zh-CN']).toBe(waiting.parts['zh-CN'])
  expect(readPreviewFrame(steps, 1600).parts['zh-CN'][0]).toMatchObject({ kind: 'reasoning', content: '我' })
  const finished = readPreviewFrame(steps, 4900)
  expect(finished.done).toBe(true)
  expect(finished.parts['zh-CN'].map((part) => part.kind)).toEqual(['reasoning', 'markdown'])
})

it('crosses the real tool-group threshold with stable IDs and leaves the completed group visible', () => {
  const original = JSON.stringify(initialPreviewParts)
  const steps = createPreviewScript('tool-group', 'group-demo', initialPreviewParts)
  const presentations = new Map<number, string>()
  for (const step of steps) {
    const tools = step.parts['zh-CN'].filter((part) => part.kind === 'tool_call')
    if (!tools.length) continue
    const group = createMessageRenderPlan(projectDesktopContentParts(step.parts['zh-CN'])).find((item) => item.kind === 'group')!
    expect(group.id).toBe('group-group-demo-tool-1')
    presentations.set(tools.length, group.presentation)
  }
  expect([...presentations]).toEqual([[1, 'flat'], [2, 'flat'], [3, 'flat'], [4, 'grouped'], [5, 'grouped']])
  const final = readPreviewFrame(steps, steps.reduce((sum, step) => sum + step.duration, 0))
  expect(final.done).toBe(true)
  expect(final.parts['zh-CN'].map((part) => part.kind)).toEqual(['markdown', ...Array(5).fill('tool_call')])
  expect(final.parts['zh-CN'].slice(1).every((part) => part.metadata?.status === 'completed')).toBe(true)
  expect(JSON.stringify(initialPreviewParts)).toBe(original)
})

it.each<PreviewMode>(['sequence', 'first-token', 'tools', 'answer', 'tool-group'])('provides synchronized English fixtures throughout %s', (mode) => {
  const steps = createPreviewScript(mode, 'localized', initialPreviewParts)
  expect(JSON.stringify(initialPreviewParts.en)).not.toMatch(/[\u4e00-\u9fff]/)
  for (const step of steps) {
    expect(JSON.stringify(step.parts.en)).not.toMatch(/[\u4e00-\u9fff]/)
    expect(step.parts.en.map((part) => [part.id, part.kind, part.metadata?.status]))
      .toEqual(step.parts['zh-CN'].map((part) => [part.id, part.kind, part.metadata?.status]))
  }
})
