import { messages, type Locale } from './catalog'

// Translate application-owned labels and diagnostics at the display boundary.
// Conversation text, questions, filenames and custom tool output stay unchanged.
const systemMessages: ReadonlyArray<readonly [string, string]> = [
  ...Object.values(messages),
  ['无法加载更多对话。', 'Unable to load more conversations.'],
  ['Agent 状态读取失败。', 'Unable to read the agent status.'],
  ['Agent 连接中断，正在恢复。', 'Agent connection interrupted. Reconnecting.'],
  ['当前客户端不支持 Agent。', 'This client does not support the agent.'],
  ['CornAgent 尚未配置模型和 Redis。', 'Configure the model and Redis to use CornAgent.'],
  ['无法开始 Agent 对话。', 'Unable to start the conversation.'],
  ['当前客户端不支持文件上传。', 'This client does not support file uploads.'],
  ['当前客户端不支持删除会话。', 'This client does not support deleting conversations.'],
  ['无法删除会话。', 'Unable to delete the conversation.'],
  ['无法加载更早消息。', 'Unable to load earlier messages.'],
  [
    '消息分支状态尚未同步，请刷新会话后重试。',
    'The message branch has not synced yet. Refresh the conversation and try again.',
  ],
  ['文件处理失败。', 'Unable to process the file.'],
  ['自动审核中', 'Reviewing request'],
  ['正在审查此请求', 'Reviewing this request'],
  ['自动审批拒绝', 'Request declined'],
  ['自动审批判定请求不应执行。', 'The request was declined by automatic review.'],
  ['正在读取文件', 'Reading file'],
  ['已读取文件', 'Read file'],
  ['读取文件', 'Read file'],
  ['询问更多内容', 'Ask a question'],
  ['已询问更多内容', 'Question asked'],
  ['请求失败，请重试。', 'Failed to fetch'],
]
const indexes = {
  'zh-CN': new Map(systemMessages.map(([zh, en]) => [en, zh])),
  en: new Map(systemMessages.map(([zh, en]) => [zh, en])),
}

export function localizeSystemMessage(value: string, locale: Locale): string {
  const exact = indexes[locale].get(value)
  if (exact) return exact
  if (locale !== 'en') return value
  return value
    .replace(/^最多可添加 (\d+) 个文件。$/, 'You can attach up to $1 files.')
    .replace(/^最多可添加 (\d+) 个 PDF。$/, 'You can attach up to $1 PDFs.')
    .replace(/^此格式最多可添加 (\d+) 个文件。$/, 'You can attach up to $1 files in this format.')
    .replace(/^不支持 (.+) 的文件格式。$/, 'Unsupported file format: $1.')
    .replace(/^(.+) 不能超过 (.+)。$/, '$1 must not exceed $2.')
    .replace(/^文件合计不能超过 (.+)。$/, 'Total file size must not exceed $1.')
    .replace(/已执行 (\d+) 个子任务/g, 'Executed $1 subtasks')
    .replace(/已编排子任务 (\d+) 次/g, 'Orchestrated subtasks $1 times')
    .replace(/已等待子任务 (\d+) 次/g, 'Waited for subtasks $1 times')
    .replace(/^正在执行子任务：(.+)$/, 'Running subtask: $1')
    .replace(/^已执行子任务：(.+)$/, 'Subtask finished: $1')
    .replace(/已运行 (\d+) 条命令/g, 'Ran $1 commands')
    .replace(/已搜索 (\d+) 个文件 \/ (\d+) 次搜索/g, 'Searched $1 files in $2 searches')
    .replace(/已搜索 (\d+) 次/g, 'Searched $1 times')
    .replace(/已编辑 (\d+) 次文件/g, 'Made $1 file edits')
    .replace(/已处理 (\d+) 次文件交付/g, 'Processed $1 file deliveries')
    .replace(/已校验 (\d+) 次/g, 'Ran $1 checks')
    .replace(/已更新 (\d+) 次任务/g, 'Updated $1 tasks')
    .replace(/已同步 (\d+) 次/g, 'Synced $1 times')
    .replace(/已思考 (\d+) 次/g, 'Reasoned $1 times')
    .replace(/已处理 (\d+) 个步骤/g, 'Processed $1 steps')
    .replace(/^已处理 (.+)$/, 'Processed in $1')
}
