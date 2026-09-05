import type { AgentContentPart } from '../agent/types'

export type PreviewMode = 'sequence' | 'first-token' | 'tools' | 'answer'
export interface PreviewStep { duration: number; parts: AgentContentPart[]; streamId?: string }

export const initialPreviewParts: AgentContentPart[] = [
  { id: 'reasoning-1', kind: 'reasoning', content: '先明确任务范围，再并行收集资料。' },
  { id: 'question-1', kind: 'user_question', content: '', metadata: { status: 'answered', answer_content: '直接演示完整拆分过程', selected_option_id: 'demo' } },
  { id: 'body-1', kind: 'markdown', content: '任务已拆分为三个独立的方向。\n\n下面继续核对证据，随后汇总结果。' },
  { id: 'tool-1', kind: 'tool_call', title: '已读取示例资料', content: '已读取三份示例文件。' },
  { id: 'wait-1', kind: 'tool_call', content: '', metadata: { tool_name: 'wait_subagents', task_count: 3, status: 'completed' } },
]

const answer = '新一轮核验已完成。之前的正文和工具现在收入上方过程区。\n\n这段正文会继续流式增长，收起动画保持连贯。\n\n### 核验结果\n| 检查项 | 结果 |\n| --- | --- |\n| 示例资料 | 齐全 |\n| 任务分工 | 清晰 |\n\n可以继续播放工具或新正文，观察渲染与收起效果。'

/** Deterministic presentation frames; no transport, model, or persisted session. */
export function createPreviewScript(mode: PreviewMode, prefix: string, existing: AgentContentPart[]): PreviewStep[] {
  const steps: PreviewStep[] = []
  let parts = mode === 'sequence' || mode === 'first-token' ? [] : existing
  const append = (part: AgentContentPart, duration: number, stream = false) => {
    parts = [...parts, part]
    steps.push({ duration, parts, streamId: stream ? part.id : undefined })
  }
  const finishTool = () => {
    parts = parts.map((part, index) => index === parts.length - 1
      ? { ...part, title: part.title?.replace('正在', '已'), content: '示例检查已完成。', metadata: { ...part.metadata, status: 'completed' } }
      : part)
  }
  if (mode === 'sequence' || mode === 'first-token') {
    steps.push({ duration: 1600, parts })
    append({ id: `${prefix}-reasoning`, kind: 'reasoning', title: '正在思考', content: '我会先读取示例资料，再核对结论，最后给出结构化回答。' }, 1800, true)
    append({ id: `${prefix}-intro`, kind: 'markdown', content: '我会把任务拆成资料阅读和结果核验两步。\n\n现在开始读取示例文件。' }, 1500, true)
  }
  if (mode === 'first-token') return steps
  if (mode !== 'answer') {
    append({ id: `${prefix}-read`, kind: 'tool_call', title: '正在读取示例资料', content: '', metadata: { tool_name: 'read_file', status: 'running' } }, 3200)
    finishTool()
    steps.push({ duration: 900, parts })
    append({ id: `${prefix}-check`, kind: 'tool_call', title: '正在核对示例结果', content: '', metadata: { status: 'running' } }, 3200)
    finishTool()
    steps.push({ duration: 800, parts })
  }
  if (mode !== 'tools') append({ id: `${prefix}-answer`, kind: 'markdown', content: answer }, 2800, true)
  return steps
}

export function readPreviewFrame(steps: PreviewStep[], elapsed: number) {
  let remaining = elapsed
  for (const step of steps) {
    if (remaining < step.duration) return {
      done: false,
      parts: step.streamId ? step.parts.map((part) => part.id === step.streamId
        ? { ...part, content: part.content.slice(0, Math.max(1, Math.ceil(part.content.length * remaining / step.duration))) }
        : part) : step.parts,
    }
    remaining -= step.duration
  }
  return { done: true, parts: steps.at(-1)?.parts ?? [] }
}
