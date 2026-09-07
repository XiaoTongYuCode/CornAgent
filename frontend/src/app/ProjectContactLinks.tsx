import { GithubOutlined, XOutlined } from '@ant-design/icons'

export function ProjectContactLinks() {
  return (
    <div className="agent-new-conversation__social-links">
      <a href="https://github.com/XiaoTongYuCode/CornAgent" target="_blank" rel="noopener noreferrer" aria-label="GitHub" title="GitHub">
        <GithubOutlined aria-hidden="true" />
      </a>
      <a href="https://x.com/tongyu_xiao" target="_blank" rel="noopener noreferrer" aria-label="X" title="X">
        <XOutlined aria-hidden="true" />
      </a>
    </div>
  )
}
