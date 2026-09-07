export interface MessageRenderContentPart {
  id: string
  kind: 'markdown' | 'reasoning' | 'tool_call' | 'user_question'
  content: string
  title?: string | null
  metadata?: Record<string, unknown> | null
}

export interface MessageRenderPartItem {
  index: number
  kind: 'part'
}

export interface MessageRenderGroupItem {
  id: string
  indexes: number[]
  kind: 'group'
  presentation: 'flat' | 'grouped'
  title: string
}

export type MessageRenderPlanItem = MessageRenderPartItem | MessageRenderGroupItem

type ToolActionBucket =
  | 'check'
  | 'command'
  | 'deliverable'
  | 'edit'
  | 'search'
  | 'sync'
  | 'task'
  | 'subagent'
  | 'subagentControl'
  | 'subagentWait'
  | 'other'

const FLAT_COLLAPSIBLE_RUN_MAX_ITEM_COUNT = 3

const TOOL_NAME_PREFIXES = [
  'desktop_fs__',
  'developer__',
  'el__',
  'desktop_fs / ',
  'developer / ',
  'el / ',
  'desktop_fs/',
  'developer/',
  'el/',
]
const FILE_EDIT_OPERATIONS = ['write', 'edit', 'patch', 'jsonl_append']
const FILE_LOOKUP_OPERATIONS = ['read', 'search', 'tree']
const TOOL_ACTION_BUCKET_BY_NAME: Partial<Record<string, ToolActionBucket>> = {
  read_url: 'search',
  mock_web_search: 'search',
  spawn_subagents: 'subagentControl',
  list_subagents: 'subagentControl',
  collect_subagent_results: 'subagentControl',
  delegate_tasks: 'subagentControl',
  wait_subagents: 'subagentWait',
  create_company_research_report: 'task',
  generate_document: 'deliverable',
  generate_xlsx: 'deliverable',
  get_company_index_evidence_slice: 'search',
  get_company_index_job: 'search',
  get_company_research_report_content: 'search',
  get_deepwiki_report_content: 'search',
  get_deepwiki_report_metadata: 'search',
  get_document_render_schema: 'deliverable',
  get_induchain_chain_context: 'search',
  get_news_feed_item: 'search',
  list_company_index_files: 'search',
  list_deepwiki_reports: 'search',
  list_my_report_creation_tasks: 'task',
  list_news_feed_items: 'search',
  read_company_index_file: 'search',
  render_file_deliverable: 'deliverable',
  search_company_index_evidence: 'search',
  search_company_info: 'search',
  search_induchain_chains: 'search',
  select_company_entity: 'search',
  unified_search: 'search',
  validate_render_request: 'check',
  web_search_batch: 'search',
  web_search: 'search',
  ground_company_index: 'search',
}

export function isCollapsibleMessagePart(part: MessageRenderContentPart): boolean {
  return part.kind === 'reasoning' || part.kind === 'tool_call'
}

function normalizeReasoningValue(value?: string | null): string {
  return value?.trim() ?? ''
}

function getStringMetadata(metadata: Record<string, unknown> | null | undefined, key: string): string {
  const value = metadata?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

function normalizeToolName(value: string): string {
  let name = value.trim()
  for (const prefix of TOOL_NAME_PREFIXES) {
    if (name.startsWith(prefix)) {
      name = name.slice(prefix.length)
      break
    }
  }
  return name.replaceAll(' ', '_')
}

function getToolActionBucket(
  title: string,
  metadata: Record<string, unknown> | null | undefined,
): ToolActionBucket {
  if (metadata?.subagent === true) return 'subagent'
  const operation = normalizeToolName(getStringMetadata(metadata, 'operation'))
  const toolName = normalizeToolName(getStringMetadata(metadata, 'tool_name'))
  const toolBucket = TOOL_ACTION_BUCKET_BY_NAME[toolName] ??
    TOOL_ACTION_BUCKET_BY_NAME[operation]
  if (toolBucket) {
    return toolBucket
  }
  if (operation === 'shell' || toolName === 'shell') {
    return 'command'
  }
  if (FILE_EDIT_OPERATIONS.includes(operation) ||
    FILE_EDIT_OPERATIONS.includes(toolName)
  ) {
    return 'edit'
  }
  if (
    operation === 'render_file_deliverable' ||
    toolName === 'render_file_deliverable' ||
    toolName === 'get_document_render_schema'
  ) {
    return 'deliverable'
  }
  if (operation === 'validate_render_request' || toolName === 'validate_render_request') {
    return 'check'
  }
  if (FILE_LOOKUP_OPERATIONS.includes(operation) ||
    FILE_LOOKUP_OPERATIONS.includes(toolName)
  ) {
    return 'search'
  }
  if (toolName.includes('ensure_company_index_local')) {
    return 'sync'
  }
  if (title.includes('运行命令')) {
    return 'command'
  }
  if (
    title.includes('公开来源') ||
    title.includes('联网') ||
    title.includes('公网') ||
    title.includes('热点新闻') ||
    title.includes('新闻详情') ||
    title.includes('新闻洞察') ||
    title.includes('产业链') ||
    title.includes('供应商') ||
    title.includes('产品服务') ||
    title.includes('公司主体') ||
    title.includes('企业信息') ||
    title.includes('档案任务') ||
    title.includes('公司证据') ||
    title.includes('证据切片') ||
    title.includes('档案文件') ||
    title.includes('公司档案') ||
    title.includes('热点报告') ||
    title.includes('相关报告') ||
    title.includes('报告正文') ||
    title.includes('报告元信息') ||
    title.includes('企业研究报告')
  ) {
    return 'search'
  }
  if (
    title.includes('生成文档') ||
    title.includes('生成表格') ||
    title.includes('XLSX') ||
    title.includes('xlsx')
  ) {
    return 'deliverable'
  }
  if (
    title.includes('编辑') ||
    title.includes('修改') ||
    title.includes('追加') ||
    title.includes('写入') ||
    title.includes('创建')
  ) {
    return 'edit'
  }
  if (
    title.includes('渲染') ||
    title.includes('文件交付') ||
    title.includes('交付文件') ||
    title.includes('生成文件')
  ) {
    return 'deliverable'
  }
  if (title.includes('校验') || title.includes('验证')) {
    return 'check'
  }
  if (title.includes('更新任务') || title.includes('任务列表')) {
    return 'task'
  }
  if (title.includes('同步')) {
    return 'sync'
  }
  if (
    title.startsWith('Read ') ||
    title.includes('搜索') ||
    title.includes('检索') ||
    title.includes('查询') ||
    title.includes('查看') ||
    title.includes('读取') ||
    title.includes('列出') ||
    title.includes('定位') ||
    title.includes('获取') ||
    title.includes('检查')
  ) {
    return 'search'
  }
  return 'other'
}

function summarizeCollapsibleGroup(parts: MessageRenderContentPart[]): string {
  const counts = parts.reduce(
    (current, part) => {
      if (part.kind === 'reasoning') {
        return {
          ...current,
          reasoning: current.reasoning + 1,
        }
      }

      const bucket = getToolActionBucket(
        normalizeReasoningValue(part.title),
        part.metadata,
      )
      const filesMatched = typeof part.metadata?.files_matched === 'number'
        ? part.metadata.files_matched
        : 0
      return {
        ...current,
        [bucket]: current[bucket] + 1,
        searchFiles: current.searchFiles + (
          bucket === 'search' ? filesMatched : 0
        ),
      }
    },
    {
      subagent: 0,
      subagentControl: 0,
      subagentWait: 0,
      command: 0,
      check: 0,
      deliverable: 0,
      edit: 0,
      other: 0,
      reasoning: 0,
      search: 0,
      searchFiles: 0,
      sync: 0,
      task: 0,
    },
  )
  const segments = [
    counts.subagent > 0 ? `已执行 ${counts.subagent} 个子任务` : null,
    counts.subagentControl > 0 ? `已编排子任务 ${counts.subagentControl} 次` : null,
    counts.subagentWait > 0 ? `已等待子任务 ${counts.subagentWait} 次` : null,
    counts.command > 0 ? `已运行 ${counts.command} 条命令` : null,
    counts.search > 0
      ? counts.searchFiles > 0
        ? `已搜索 ${counts.searchFiles} 个文件 / ${counts.search} 次搜索`
        : `已搜索 ${counts.search} 次`
      : null,
    counts.edit > 0 ? `已编辑 ${counts.edit} 次文件` : null,
    counts.deliverable > 0 ? `已处理 ${counts.deliverable} 次文件交付` : null,
    counts.check > 0 ? `已校验 ${counts.check} 次` : null,
    counts.task > 0 ? `已更新 ${counts.task} 次任务` : null,
    counts.sync > 0 ? `已同步 ${counts.sync} 次` : null,
    counts.reasoning > 0 ? `已思考 ${counts.reasoning} 次` : null,
    counts.other > 0 ? `已处理 ${counts.other} 个步骤` : null,
  ].filter(Boolean)

  return segments.length > 0
    ? segments.join(' ')
    : `已处理 ${parts.length} 个步骤`
}

function createCollapsibleGroup(
  indexes: number[],
  parts: MessageRenderContentPart[],
): MessageRenderGroupItem {
  const groupParts = indexes.map((partIndex) => parts[partIndex])
  const firstPart = groupParts[0]

  return {
    id: firstPart ? `group-${firstPart.id}` : `group-${indexes[0] ?? 0}`,
    indexes,
    kind: 'group',
    presentation: groupParts.length > FLAT_COLLAPSIBLE_RUN_MAX_ITEM_COUNT
      ? 'grouped'
      : 'flat',
    title: summarizeCollapsibleGroup(groupParts),
  }
}

export function createMessageRenderPlan(
  parts: MessageRenderContentPart[],
): MessageRenderPlanItem[] {
  const plan: MessageRenderPlanItem[] = []
  let index = 0

  while (index < parts.length) {
    const part = parts[index]
    if (!part || !isCollapsibleMessagePart(part)) {
      plan.push({
        index,
        kind: 'part',
      })
      index += 1
      continue
    }

    let endIndex = index + 1
    while (endIndex < parts.length && isCollapsibleMessagePart(parts[endIndex])) {
      endIndex += 1
    }

    const indexes = Array.from(
      { length: endIndex - index },
      (_value, offset) => index + offset,
    )
    // 从首个 reasoning/tool part 起创建稳定父节点，后续只追加子项并切换展示形态。
    plan.push(createCollapsibleGroup(indexes, parts))

    index = endIndex
  }

  return plan
}
