import { createPreviewScript, initialPreviewParts, readPreviewFrame } from './messagePreviewScript'

it('shows running tools long enough to preview shimmer, then completes them without adding a body', () => {
  const steps = createPreviewScript('tools', 'demo', initialPreviewParts)
  expect(readPreviewFrame(steps, 2000).parts.at(-1)?.title).toBe('正在读取示例资料')
  expect(readPreviewFrame(steps, 3500).parts.at(-1)).toMatchObject({ id: 'demo-read', title: '已读取示例资料' })
  const secondTool = readPreviewFrame(steps, 5000)
  expect(secondTool.parts.at(-2)?.title).toBe('已读取示例资料')
  expect(secondTool.parts.at(-1)?.title).toBe('正在核对示例结果')
  const finished = readPreviewFrame(steps, 8100)
  expect(finished.done).toBe(true)
  expect(finished.parts.at(-1)?.title).toBe('已核对示例结果')
  expect(finished.parts.filter((part) => part.kind === 'markdown')).toHaveLength(1)
})

it('waits for the first token before reasoning and moves the final body boundary while streaming', () => {
  const steps = createPreviewScript('sequence', 'demo', initialPreviewParts)
  expect(readPreviewFrame(steps, 0).parts).toEqual([])
  expect(readPreviewFrame(steps, 1600).parts.map((part) => part.kind)).toEqual(['reasoning'])
  const beforeAnswer = steps.slice(0, -1).reduce((duration, step) => duration + step.duration, 0)
  expect(readPreviewFrame(steps, beforeAnswer - 1).parts.at(-1)?.kind).toBe('tool_call')
  expect(readPreviewFrame(steps, beforeAnswer).parts.at(-1)).toMatchObject({ id: 'demo-answer', kind: 'markdown', content: '新' })
  expect(readPreviewFrame(steps, beforeAnswer + 2800).done).toBe(true)
  expect(initialPreviewParts).toHaveLength(5)
})

it('replays the first-token transition independently and reuses static frames', () => {
  const steps = createPreviewScript('first-token', 'token', initialPreviewParts)
  const waiting = readPreviewFrame(steps, 0)
  expect(waiting.parts).toEqual([])
  expect(readPreviewFrame(steps, 1500).parts).toBe(waiting.parts)
  expect(readPreviewFrame(steps, 1600).parts[0]).toMatchObject({ kind: 'reasoning', content: '我' })
  const finished = readPreviewFrame(steps, 4900)
  expect(finished.done).toBe(true)
  expect(finished.parts.map((part) => part.kind)).toEqual(['reasoning', 'markdown'])
})
