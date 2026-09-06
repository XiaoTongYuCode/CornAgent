import type { Locale } from '../i18n'

const zh = {
  initialReasoning: '先明确任务范围，再并行收集资料。',
  questionAnswer: '直接演示完整拆分过程',
  initialBody: '任务已拆分为三个独立的方向。\n\n下面继续核对证据，随后汇总结果。',
  initialToolResult: '已读取三份示例文件。',
  reasoning: '我会先读取示例资料，再核对结论，最后给出结构化回答。',
  intro: '我会把任务拆成资料阅读和结果核验两步。\n\n现在开始读取示例文件。',
  readRunning: '正在读取示例资料',
  readDone: '已读取示例资料',
  checkRunning: '正在核对示例结果',
  checkDone: '已核对示例结果',
  toolResult: '示例检查已完成。',
  groupIntro: '依次执行 5 个示例工具：前 3 个逐项展示，第 4 个出现时自动收起为工具组。\n\n可以暂停观察，或展开工具组查看后续步骤。',
  groupRunning: '正在执行示例工具 {count}',
  groupDone: '已执行示例工具 {count}',
  answer: '新一轮核验已完成。之前的正文和工具现在收入上方过程区。\n\n这段正文会继续流式增长，收起动画保持连贯。\n\n### 核验结果\n| 检查项 | 结果 |\n| --- | --- |\n| 示例资料 | 齐全 |\n| 任务分工 | 清晰 |\n\n可以继续播放工具或新正文，观察渲染与收起效果。',
}

// Synthetic model output has its own complete fixtures; real conversations are never translated.
export const messagePreviewCopy = {
  'zh-CN': zh,
  en: {
    initialReasoning: 'First define the scope, then gather the evidence in parallel.',
    questionAnswer: 'Show the complete task breakdown',
    initialBody: 'The task is split into three independent workstreams.\n\nNext, I will verify the evidence and bring the results together.',
    initialToolResult: 'Read three example files.',
    reasoning: 'I will read the sample material, verify the conclusions, and then provide a structured answer.',
    intro: 'I will split the task into reading the material and verifying the results.\n\nStarting with the example files.',
    readRunning: 'Reading sample material',
    readDone: 'Sample material read',
    checkRunning: 'Checking sample results',
    checkDone: 'Sample results checked',
    toolResult: 'The sample check is complete.',
    groupIntro: 'Running five example tools in order. The first three appear individually; when the fourth arrives, they automatically collapse into a tool group.\n\nPause to inspect the transition, or expand the group to follow the remaining steps.',
    groupRunning: 'Running example tool {count}',
    groupDone: 'Example tool {count} completed',
    answer: 'Verification is complete. The earlier answer and tools are now in the process section above.\n\nThis answer will continue streaming while the folding animation stays smooth.\n\n### Verification results\n| Check | Result |\n| --- | --- |\n| Sample material | Complete |\n| Task assignments | Clear |\n\nPlay more tools or a new answer to explore the rendering and folding transitions.',
  },
} satisfies Record<Locale, Record<keyof typeof zh, string>>
