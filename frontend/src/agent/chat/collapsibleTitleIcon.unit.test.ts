import { CircleAlert, FileText, Globe, Search, ToolCase } from 'lucide-react'
import { getToolCallIcon } from './collapsibleTitleIcon'

it('uses stable tool identity across translated titles, with a fallback and failure override', () => {
  for (const [name, icon] of [['read_file', FileText], ['read_url', Globe], ['web_search', Search], ['custom', ToolCase]] as const) {
    for (const title of ['正在读取文件', 'Read something', '模型自定义标题']) {
      expect(getToolCallIcon({ id: 'tool', kind: 'tool_call', title, content: '', metadata: { tool_name: name } })).toBe(icon)
    }
  }
  expect(getToolCallIcon({ id: 'tool', kind: 'tool_call', content: '', metadata: { tool_name: 'read_file', status: 'failed' } })).toBe(CircleAlert)
})
