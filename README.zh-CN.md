<p align="center">
  <a href="README.md" lang="en">English</a> · <strong lang="zh-CN">简体中文</strong>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/cornagent-lockup-dark.svg" />
    <img src="assets/brand/cornagent-lockup.svg" alt="CornAgent" width="360" />
  </picture>
</p>

<p align="center">
  <strong>可独立运行，也能嵌入业务页面的开源 Web Agent。</strong><br />
  从实时对话到工具调用、并行子任务与持久化恢复，前后端一并提供。
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-171918?style=flat-square" alt="MIT 许可证" /></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-171918?style=flat-square" alt="Python 3.12 及以上" />
  <img src="https://img.shields.io/badge/React-19-171918?style=flat-square" alt="React 19" />
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#嵌入业务页面">嵌入页面</a> ·
  <a href="docs/subagents.md">扩展工具</a> ·
  <a href="#故障恢复与数据持久化">故障恢复</a> ·
  <a href="#文档">文档</a>
</p>

<p align="center">
  <a href="https://cornagent.xiaotongyu.com/rendering">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/rendering-dark.gif" />
      <img src="docs/screenshots/rendering-light.gif" alt="CornAgent 英文演示：思考、工具调用、流式回答与过程自动收起，循环播放" width="960" />
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://cornagent.xiaotongyu.com/rendering">查看 Demo 演示</a>
</p>

## 为什么使用 CornAgent

搭建 Agent 产品，除了模型调用，还需要处理会话、流式事件、工具执行、暂停、恢复和界面交互。CornAgent 将这些能力组织成一个可独立安装的 React + FastAPI 项目，聊天页与侧边栏共享同一套运行时。

| 能力 | 已提供的行为 |
| --- | --- |
| 实时对话 | SSE 流式回复、思考过程、工具分组，以及 Markdown、代码块和表格渲染 |
| 暂停与恢复 | Agent 提问后等待用户；支持刷新恢复与服务重启后的安全检查点接管，见[恢复边界](#故障恢复与数据持久化) |
| 并行子任务 | 主 Agent 派发、等待和收取子任务结果；支持取消、历史恢复与过程展示 |
| 会话与分支 | 历史分页、编辑消息、重新生成、切换分支与删除会话 |
| 图片与 PDF | 上传附件，按需分页读取 PDF；本地或 S3 兼容存储 |
| 页面内集成 | 独立聊天页与可调整宽度的侧边栏共用 Provider、会话和消息组件 |
| 界面偏好 | 中英文、深浅主题、可折叠导航与窄屏布局 |

## 快速开始

准备 **Python 3.12、uv、Node.js 22+、PostgreSQL 和 Redis**。已有本机 PostgreSQL / Redis 时，可以直接使用。

```sh
git clone https://github.com/XiaoTongYuCode/CornAgent.git
cd CornAgent
cp -n .env.example .env
```

编辑根目录 `.env`，填入模型 API 密钥，并确认数据库与 Redis 连接。配置完成后：

```sh
make setup
make dev
```

打开 **[http://127.0.0.1:5173/chat](http://127.0.0.1:5173/chat)**。

`make setup` 安装锁定的前后端依赖，创建 `cornagent` 数据库并执行迁移。默认 PostgreSQL 使用当前系统用户、本机 5432 端口；Redis 使用本机 6379 端口。

### 模型与配置

所有配置集中在根目录 [.env.example](.env.example)，本机使用 `.env` 覆盖；系统环境变量优先。修改配置后重启服务。

- **模型**：通过 LiteLLM 接入，默认配置使用 DeepSeek，也可连接兼容 OpenAI 的聊天与工具调用接口。图片输入需要模型支持视觉能力。
- **持久化**：PostgreSQL 保存会话、消息与运行状态，Redis Stream 传输实时事件。
- **附件**：支持本地文件系统和 S3 兼容对象存储。
- **运行参数**：监听地址、端口、并发、超时、上下文预算及附件限制均可配置。

模型密钥只在服务端使用，`.env` 不进入版本控制。未配置模型密钥时，服务仍能启动并读取历史，界面会显示 Agent 暂不可用。

## 嵌入业务页面

在本项目中，使用三个组件即可在页面内接入 Agent：

```tsx
import { AgentLauncher, AgentSidebar, CornAgentProvider } from './agent'
import './styles.css'

export default function App() {
  return (
    <CornAgentProvider>
      <main>
        <h1>我的业务页面</h1>
        <AgentLauncher />
      </main>
      <AgentSidebar />
    </CornAgentProvider>
  )
}
```

同一 Provider 下的聊天页、按钮与面板共享会话。自定义 API 路径、请求适配器和页面布局，见 **[前端接入指南](docs/frontend-integration.md)**。组件随源码提供，当前没有独立的 npm 发布包。

| 页面 | 用途 |
| --- | --- |
| `/chat` | 首页与新对话；首次发送时创建会话 |
| `/chat/:id` | 对话详情、实时过程、提问回答与消息分支 |
| `/sidebar` | 在业务页面中打开 Agent 面板的完整示例 |
| `/rendering` | 用合成内容演示流式文字、工具标题与过程折叠 |

## 工具与子任务

内置 `ask_user`、`read_file`、`web_search`、`read_url`，以及五个子任务编排工具。主 Agent 可以继续工作，再按需等待和收取子任务结果；子任务也有独立的持久化状态与取消机制。

`web_search` 使用 Tavily（在 `.env` 配置 `tavily_api_key`），`read_url` 使用无需密钥的 Jina Reader，主 Agent 与子 Agent 均可使用。详见[网络工具](docs/web-tools.md)。

可选的 `mock_web_search` 默认关闭，返回固定的虚构资料，用于演示搜索与任务编排，界面和模型提示均会标注“模拟”。主 Agent 和子 Agent 的推理仍使用你配置的模型接口。

工具注册、参数协议、子任务生命周期与演示提示见 **[子任务与工具扩展](docs/subagents.md)**。

## 运行架构

```text
React 聊天页 / Agent 侧边栏
            │ JSON · 文件上传 · SSE
            ▼
       FastAPI / Agent 运行时
            ├── LiteLLM → 模型与工具调用
            ├── PostgreSQL → 会话、消息树、检查点与任务状态
            ├── Redis Stream → 实时事件与有限重放
            └── 本地文件系统 / S3 → 私有附件
```

PostgreSQL 是持久状态的事实来源，Redis 负责实时事件传输。页面刷新与服务重启的恢复行为见下文。

详细边界见 [架构](docs/architecture.md)、[运行时](docs/runtime.md) 与 [文件存储](docs/storage.md)。

## 故障恢复与数据持久化

会话、消息分支、运行检查点、待回答问题与子任务状态保存在 PostgreSQL。应用进程宕机重启后，后台协调器检查过期租约，从安全检查点接管可恢复的运行；租约与递增的执行凭证（fence）阻止旧执行器继续写入运行状态。

| 中断场景 | 恢复行为 |
| --- | --- |
| 页面刷新、SSE 断线或 Redis 事件丢失 | 重连时先读取数据库快照，再接续增量事件；已落库的会话事实保留 |
| 模型回复生成中宕机 | 从安全检查点重试中断的模型轮次；未完成草稿可能被替换，不保证逐字续写 |
| 等待用户回答时重启 | 保留问题与等待状态；用户回答后继续同一次运行 |
| 等待子任务时重启 | 恢复任务状态并继续协调；已完成结果复用，租约过期的只读子任务可在原截止时间内重跑 |
| 普通工具批次执行中宕机 | 外部操作结果无法确定时，将当前运行标记为失败，保留会话历史；不自动重放，避免重复产生副作用 |

**会话数据保留与当前运行自动继续是两项不同的保证。** 对执行中断的普通工具，需要先核实外部操作结果再决定是否重试；运行失败不表示外部操作一定没有发生。

恢复以 PostgreSQL 和附件存储完好、重启后仍连接同一份持久化数据为前提；继续执行还需要 Redis、模型等依赖恢复可用。数据库及附件应使用持久存储，多实例共享附件卷或 S3 兼容桶。备份必须同时覆盖数据库与附件，不能依赖容器临时文件系统。

上述机制覆盖应用进程故障恢复。数据库或磁盘损毁、整机丢失等灾难需要部署方配置备份、存储高可用与恢复演练；项目不承诺任意故障下零数据丢失或固定恢复时间。

检查点、租约与工具失败语义见 [Agent 运行时](docs/runtime.md)，持久存储要求见 [文件存储](docs/storage.md)，已记录的恢复测试范围见 [测试与验证](docs/verification.md)。

## 开发与构建

```sh
make check   # 后端 lint / 测试，前端 lint / 测试
make build   # TypeScript 检查与前端生产构建
```

构建后，可以由 FastAPI 同源托管前端：

```sh
cd server
CORNAGENT_SERVER_RELOAD=false uv run python -m app.serve
```

升级已有安装时，先停止服务，再执行数据库迁移：

```sh
cd server
uv run alembic upgrade head
```

真实 PostgreSQL / Redis 回归会创建并清理自己的随机 schema，不清空已有数据库或 Redis：

```sh
cd server
CORNAGENT_TEST_POSTGRES_URL=postgresql+psycopg://localhost:5432/cornagent \
CORNAGENT_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run pytest -q
```

项目默认监听本机，所有浏览器共用一个工作区。对外提供服务时，需由宿主系统配置访问控制；当前没有内置登录与多租户隔离。

## 文档

| 文档 | 内容 |
| --- | --- |
| [前端说明](frontend/README.md) | 页面组织、主题、多语言与消息交互 |
| [前端接入](docs/frontend-integration.md) | Provider、开启按钮、侧边栏与宿主配置 |
| [后端说明](server/README.md) | 服务启动、依赖、配置与检查 |
| [架构说明](docs/architecture.md) | 模块分工与请求链路 |
| [Agent 运行时](docs/runtime.md) | 状态机、恢复、SSE 与消息树 |
| [子任务与工具](docs/subagents.md) | 并行任务、工具扩展与演示 |
| [文件存储](docs/storage.md) | 附件读写、会话隔离与回收 |
| [测试与验证](docs/verification.md) | 回归范围与界面验证记录 |
| [品牌资产](assets/brand/README.md) | SVG 图标、字标与使用方式 |

## 参与贡献

欢迎通过 Issue 提交问题或讨论功能，通过 Pull Request 贡献改进。提交前运行 `make check` 与 `make build`；涉及状态机、SSE、存储或消息分支时，同时验证刷新与恢复行为。请勿提交密钥、用户会话、上传文件或运行时数据。

更新本 README 时，请同步维护[英文版本](README.md)，包括示例、链接与行为说明。

## 许可

CornAgent 使用 **[MIT 许可证](LICENSE)**。移植来源与第三方依赖说明见 [NOTICE](NOTICE)。

可选用户系统默认关闭，见[鉴权配置与扩展接口](docs/authentication.md)。
