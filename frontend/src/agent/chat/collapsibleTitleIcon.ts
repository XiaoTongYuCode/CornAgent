import {
  Brain,
  FileText,
  Globe,
  MessageCircleQuestion,
  ShieldCheck,
  Component,
  RotateCwSquare,
  CircleAlert,
  ClipboardCheck,
  FileCheck,
  FolderSync,
  Pencil,
  Search,
  ShieldX,
  SquareTerminal,
  ScanSearch,
  Cable,
  ToolCase,
  UserSearch,
  type LucideIcon,
} from 'lucide-react'

import type { AgentChatMessageContentPart } from './types'

const TOOL_ICONS: Readonly<Record<string, LucideIcon>> = {
  ask_user: MessageCircleQuestion,
  read_file: FileText,
  web_search: Search,
  read_url: Globe,
  mock_web_search: Search,
  spawn_subagents: Component,
  list_subagents: Component,
  collect_subagent_results: ClipboardCheck,
  wait_subagents: RotateCwSquare,
  cancel_subagents: ShieldX,
}

export function getToolCallIcon(part: AgentChatMessageContentPart): LucideIcon {
  const metadata = part.metadata
  if (metadata?.failed === true || metadata?.status === 'failed') return CircleAlert
  if (metadata?.interaction === 'tool_approval') return ShieldCheck
  const name = metadata?.tool_name
  return typeof name === 'string' && Object.hasOwn(TOOL_ICONS, name) ? TOOL_ICONS[name] : ToolCase
}

const COLLAPSIBLE_TITLE_ICON_RULES: Array<{
  icon: LucideIcon
  keywords: string[]
}> = [
    { icon: RotateCwSquare, keywords: ['等待子任务', 'Waiting for subtasks'] },
    { icon: Component, keywords: ['子任务', 'subtask', 'Subtask'] },
    {
      icon: CircleAlert,
      keywords: ['失败', '错误'],
    },
    {
      icon: ShieldX,
      keywords: ['拒绝'],
    },
    {
      icon: Brain,
      keywords: ['思考'],
    },
    {
      icon: UserSearch,
      keywords: ['正在询问更多内容', '询问更多内容'],
    },
    {
      icon: Search,
      keywords: [
        'Read',
        'Search',
        '搜索',
        '检索',
        '查询',
        '查看',
        '读取',
        '列出',
        '定位',
        '获取',
        '查找',
        '浏览',
        '公开来源',
        '新闻详情',
        '热点新闻',
        '新闻洞察',
        '产业链',
        '供应商',
        '产品服务',
        '公司证据',
        '证据切片',
        '档案文件',
        '档案任务',
        '公开网页',
        '联网',
        '公网',
      ],
    },
    {
      icon: SquareTerminal,
      keywords: ['执行', '终端', '命令'],
    },
    {
      icon: FileCheck,
      keywords: ['文件交付', '交付文件', '渲染', '生成文件', '生成文档', '生成表格', 'XLSX', 'xlsx'],
    },
    {
      icon: ScanSearch,
      keywords: ['选择', '公司主体'],
    },
    {
      icon: Pencil,
      keywords: ['写入', '追加', '编辑', '创建', '修改', '调用工具'],
    },
    {
      icon: ClipboardCheck,
      keywords: ['更新任务', '检查', '校验'],
    },
    {
      icon: Cable,
      keywords: ['MCP', 'mcp'],
    },
    {
      icon: ToolCase,
      keywords: ['Skill', 'skill'],
    },
    {
      icon: FolderSync,
      keywords: ['同步'],
    },
  ]

export function getCollapsibleTitleIcon(titleText: string): LucideIcon | null {
  if (!titleText) {
    return null
  }

  return COLLAPSIBLE_TITLE_ICON_RULES.find((rule) =>
    rule.keywords.some((keyword) => titleText.includes(keyword)),
  )?.icon ?? null
}
