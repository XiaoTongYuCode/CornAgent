# 前端接入

状态：active

公共入口为 `frontend/src/agent/index.ts`。在本 React 项目中添加业务页面时，使用统一 Provider、开启按钮和侧栏即可复用对话、文件、提问、SSE 与历史恢复，无需自行组合底层组件。

## 最小示例

```tsx
import { AgentLauncher, AgentSidebar, CornAgentProvider } from './agent'
import './styles.css'

export default function App() {
  return (
    <CornAgentProvider>
      <main>
        <h1>我的页面</h1>
        <AgentLauncher />
      </main>
      <AgentSidebar />
    </CornAgentProvider>
  )
}
```

`AgentSidebar` 默认悬浮于右侧，无需额外的布局容器；内部提供关闭、历史、宽度调整和完整聊天交互。项目 `/sidebar` 页面使用同一套组件，桌面通过 `layout="docked"` 将面板放入应用布局，窄屏自动使用悬浮面板。

自定义开启按钮时，通过 `useAgent()` 获取共享工作区：

```tsx
import { useAgent } from './agent'

function MyButton() {
  const agent = useAgent()
  return <button onClick={() => agent.setOpen(true)}>与 Agent 讨论</button>
}
```

把自定义按钮放在 `CornAgentProvider` 内。同一 Provider 下的按钮、聊天页和侧栏共享会话；不需要额外创建 gateway 或 SSE 订阅。

## 侧栏定制

所有定制参数均为可选，原来的 `<AgentSidebar />` 保持默认外观和覆盖式布局。标题、图标及业务内容由宿主传入，不需要修改组件源码：

```tsx
<AgentSidebar
  title="业务助手"
  defaultWidth={440}
  minWidth={320}
  maxWidth={800}
  widthStorageKey="my-app:assistant-width"
  className="my-assistant"
  styles={{ header: { height: 56 }, footer: { padding: 12 } }}
  footer={<small>回复仅供参考</small>}
  renderActions={({ actions }) => <>{actions.newChat}{actions.close}</>}
/>
```

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `title`、`icon` | `CornAgent`、无 | React 节点；可传品牌名称、Logo 或自定义标题内容 |
| `ariaLabel` | 纯文本标题，否则 `CornAgent` | 面板的无障碍名称；复杂标题建议显式设置 |
| `userName` | 无 | 空白会话问候中的用户名 |
| `renderHeader` | 内置头部 | 自定义头部内容；返回 `null` 隐藏整个头部 |
| `renderActions` | 新对话、历史、关闭 | 替换、重排或追加头部操作；返回 `null` 隐藏操作区 |
| `footer` | 无 | 固定在聊天区域下方的 React 节点 |
| `emptyStateFooter` | 无 | 仅空白会话时，显示在输入框下方的 React 节点 |
| `className`、`style` | 无 | 面板根节点样式；宽度通过专用参数控制，避免与退场动画冲突 |
| `classNames`、`styles` | 无 | 分别设置 `header`、`body`、`footer` 分区的类名和样式，无需依赖内部选择器 |
| `layout` | `overlay` | `overlay` 覆盖页面；`docked` 在宿主横向布局中与页面并排 |
| `defaultWidth` | `400` | 非受控初始宽度，单位 CSS px；已保存的宽度优先 |
| `width`、`onWidthChange` | 无 | 受控宽度及拖拽/键盘调整回调；宿主通过回调更新 `width` |
| `minWidth`、`maxWidth` | `400`、`720` | 宽度边界，最终受视口宽度限制；窄屏仍自动全屏覆盖 |
| `resizable` | `true` | 是否显示并启用拖拽/键盘调整手柄 |
| `widthStorageKey` | `cornagent:agent-panel-width` | 非受控宽度偏好的存储键，初始化时读取；`null` 禁用持久化。受控模式不读写宽度偏好 |

`renderHeader` / `renderActions` 接收导出的 `AgentSidebarRenderContext`：

- `defaultContent`：该区域的默认内容，便于追加业务按钮而保留内置功能。
- `actions.newChat` / `actions.history` / `actions.close`：可直接组合的内置操作，保留禁用状态和原有交互。
- `close()`：使用侧栏退场动画关闭；自定义关闭按钮调用此方法。
- `workspace`：当前共享工作区；`busy` 表示新建/切换会话暂不可用。自定义写操作应沿用该禁用状态。

回调仅渲染内容，不创建新工作区。复杂的自定义组件可定义在回调外，再通过 JSX 传入。宿主文案由宿主负责国际化，组件不会翻译传入的 React 节点。隐藏头部或关闭按钮时，宿主应保留可访问的关闭入口。

受控宽度用法：

```tsx
import { useState } from 'react'
import { AgentSidebar } from './agent'

function MySidebar() {
  const [width, setWidth] = useState(440)
  return <AgentSidebar title="业务助手" width={width} onWidthChange={setWidth} />
}
```

### 与业务页面平级

并排模式让页面和侧栏成为同一个 Flex 容器的子元素，打开和关闭时同步调整占用空间：

```tsx
<CornAgentProvider>
  <div style={{ display: 'flex', height: '100dvh', overflow: 'clip' }}>
    <main style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
      <AgentLauncher />
      {/* 业务页面 */}
    </main>
    <AgentSidebar layout="docked" title="业务助手" />
  </div>
</CornAgentProvider>
```

`docked` 的宽度由侧栏自身管理，宿主无需计时、预留固定网格列或修改侧栏的父节点。已有默认覆盖式接入无需迁移；自行覆盖旧网格布局或内部样式的接入方应使用上述 Flex 布局及公开样式参数。

## 配置

| Provider 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `apiBaseUrl` | `/api/v1` | API 路径前缀；JSON、上传、SSE 与附件地址统一使用该前缀 |
| `sessionId` | `undefined` | 自动选取最近会话；`null` 为新对话；字符串打开指定会话 |
| `principalKey` | `cornagent-local` | 客户端工作区状态键，不代表服务端身份或权限隔离 |
| `transport` | 内置 HTTP transport | 注入宿主的请求适配器；提供时优先于 `apiBaseUrl` |

默认通过同源代理访问 FastAPI，适合直接运行或嵌入同源页面。模型密钥留在服务端 `.env`，前端 Provider 不接收模型凭据。自定义 `transport` 应保持引用稳定。

Provider 统一管理主题、语言与工作区，偏好变化不会重建 gateway。样式入口包含项目的页面基础样式与主题变量；源码集成到已有应用时，应由宿主统一引入并管理基础样式。当前入口随项目源码提供。

## 用户系统接入

上述最小示例适用于用户系统关闭或宿主已建立身份的情况。项目应用层的 `AuthGate` 在挂载工作区前调用
`POST /api/v1/auth/session`：关闭模式直接进入共享工作区，无感模式自动建立 Cookie，账号模式显示登录页。
共享 `CornAgentProvider` 不主动发起登录；嵌入方应先完成同源认证，再把返回的 `user_id` 用作 `principalKey`。
身份变化时更新该键或重新挂载 Provider，避免保留上一用户的界面状态。

内置 HTTP transport 使用 `credentials: 'same-origin'`，JSON、附件和 SSE 统一携带同源 Cookie；
写请求携带 `X-CornAgent-Request: 1`。跨域接入需由宿主实现自己的认证 transport，修改 `principalKey` 本身不授予服务端权限。
完整协议及身份适配接口见[用户系统](authentication.md)。

## 组件分工

| 组件或接口 | 职责 |
| --- | --- |
| `CornAgentProvider` | 主题、语言、HTTP gateway 与持久化工作区 |
| `AgentLauncher` | 开启面板；可传入按钮文案和样式类 |
| `AgentSidebar` | 默认悬浮面板，或应用布局中的面板 |
| `useAgent` | 打开、关闭、选择会话、提交、编辑、重新生成、切换分支、取消、删除等共享操作 |
| `AgentChatPage` | 完整聊天页，传入 `workspace`、`sessionId` 与路由回调 |

`src/App.tsx` 展示路由控制方式，`src/app/SidebarExamplePage.tsx` 展示页面内开启方式。内部组件直接导入具体模块；使用方通过公共入口导入。

消息复制、编辑与分支切换已包含在聊天组件内。需要自定义消息界面时，使用 `useAgent().edit(messageId, content)`、`regenerate(messageId)` 与 `switchVersion(messageId)`；它们负责刷新消息树并衔接新运行的 SSE，调用方负责呈现错误和操作中状态。
