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
