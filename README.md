<p align="center">
  <strong lang="en">English</strong> · <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/cornagent-lockup-dark.svg" />
    <img src="assets/brand/cornagent-lockup.svg" alt="CornAgent" width="360" />
  </picture>
</p>

<p align="center">
  <strong>An open-source web agent that runs on its own or inside your application.</strong><br />
  Frontend and backend included, with streaming conversations, tool calls, parallel subtasks, and durable recovery.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-171918?style=flat-square" alt="MIT license" /></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-171918?style=flat-square" alt="Python 3.12 or later" />
  <img src="https://img.shields.io/badge/React-19-171918?style=flat-square" alt="React 19" />
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#embed-in-your-application">Integration</a> ·
  <a href="#tools-and-subtasks">Tools</a> ·
  <a href="#recovery-and-data-persistence">Recovery</a> ·
  <a href="#documentation">Documentation</a>
</p>

<p align="center">
  <a href="https://cornagent.xiaotongyu.com/rendering">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/rendering-dark.gif" />
      <img src="docs/screenshots/rendering-light.gif" alt="Looping CornAgent demo in English: reasoning, tool calls, streaming responses, and automatically collapsing process details" width="960" />
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://cornagent.xiaotongyu.com/rendering">View the Demo</a>
</p>

## Why CornAgent?

Building an agent product takes more than calling a model. It also requires sessions, streaming events, tool execution, pausing, recovery, and user interactions. CornAgent brings these capabilities together in a standalone React + FastAPI project, with a shared runtime for the chat page and sidebar.

| Capability | Included behavior |
| --- | --- |
| Live conversations | SSE streaming, reasoning, tool groups, and Markdown, code block, and table rendering |
| Pause and resume | Agents wait for user answers; page refresh recovery and safe checkpoint takeover after service restarts. See [recovery boundaries](#recovery-and-data-persistence) |
| Parallel subtasks | The main agent dispatches subtasks, waits for them, and collects results; cancellation, history recovery, and progress display are supported |
| Sessions and branches | Paginated history, message editing, response regeneration, branch switching, and session deletion |
| Images and PDFs | Attachment uploads, on-demand paginated PDF reading, and local or S3-compatible storage |
| Embedded integration | A standalone chat page and resizable sidebar share the same provider, sessions, and message components |
| Interface preferences | English and Simplified Chinese, light and dark themes, collapsible navigation, and narrow-screen layouts |

## Quick Start

Install **Python 3.12, uv, Node.js 22+, PostgreSQL, and Redis**. You can use existing local PostgreSQL and Redis instances.

```sh
git clone https://github.com/XiaoTongYuCode/CornAgent.git
cd CornAgent
cp -n .env.example .env
```

Edit `.env` in the project root to set your model API key and verify the PostgreSQL and Redis connection settings. Then run:

```sh
make setup
make dev
```

Open **[http://127.0.0.1:5173/chat](http://127.0.0.1:5173/chat)**.

`make setup` installs the locked frontend and backend dependencies, creates the `cornagent` database, and applies migrations. By default, PostgreSQL uses the current system user on local port 5432; Redis uses local port 6379.

### Models and Configuration

All configuration options are listed in [.env.example](.env.example) at the project root. Use `.env` for local overrides; system environment variables take precedence. Restart the service after changing configuration.

- **Models:** Connected through LiteLLM. The default configuration uses DeepSeek; OpenAI-compatible chat and tool-calling APIs are also supported. Image input requires a vision-capable model.
- **Persistence:** PostgreSQL stores sessions, messages, and run state; Redis Streams deliver live events.
- **Attachments:** Local filesystem and S3-compatible object storage are supported.
- **Runtime settings:** Listening addresses, ports, concurrency, timeouts, context budgets, and attachment limits are configurable.

Model API keys are used only on the server, and `.env` is excluded from version control. Without a model API key, the service can still start and load history; the interface indicates that the agent is unavailable.

## Embed in Your Application

Within this project, use three components to add an agent to a page:

```tsx
import { AgentLauncher, AgentSidebar, CornAgentProvider } from './agent'
import './styles.css'

export default function App() {
  return (
    <CornAgentProvider>
      <main>
        <h1>My Application</h1>
        <AgentLauncher />
      </main>
      <AgentSidebar />
    </CornAgentProvider>
  )
}
```

The chat page, launcher, and panel share sessions under the same provider. For custom API paths, request adapters, and page layouts, see the **[frontend integration guide](docs/frontend-integration.md)** (Simplified Chinese). Components are provided as source code; there is currently no standalone npm package.

| Route | Purpose |
| --- | --- |
| `/chat` | Home and new conversations; a session is created when the first message is sent |
| `/chat/:id` | Conversation details, live progress, user questions and answers, and message branches |
| `/sidebar` | A complete example of opening the agent panel within an application page |
| `/rendering` | Synthetic content demonstrating streaming text, tool titles, and process collapsing |

## Tools and Subtasks

Built-in tools include `ask_user`, `read_file`, `web_search`, `read_url`, and five subtask orchestration tools. The main agent can continue working, then wait for and collect subtask results as needed. Subtasks have their own durable state and cancellation mechanism.

`web_search` uses Tavily (set `tavily_api_key` in `.env`); `read_url` uses keyless Jina Reader. Both are available to the main agent and subagents. See [web tools](docs/web-tools.md).

The optional `mock_web_search` is disabled by default and returns fixed, fictional material for demonstrating search and task orchestration. Both the interface and model prompts identify it as simulated. Reasoning by the main agent and subagents still uses your configured model API.

For tool registration, parameter contracts, subtask lifecycles, and demo prompts, see **[subtasks and tool extensions](docs/subagents.md)** (Simplified Chinese).

## Architecture

```text
React Chat Page / Agent Sidebar
            │ JSON · File Uploads · SSE
            ▼
       FastAPI / Agent Runtime
            ├── LiteLLM → Models and tool calls
            ├── PostgreSQL → Sessions, message trees, checkpoints, and task state
            ├── Redis Streams → Live events and bounded replay
            └── Local Filesystem / S3 → Private attachments
```

PostgreSQL is the source of truth for durable state; Redis handles live event delivery. Recovery after page refreshes and service restarts is described below.

For detailed boundaries, see [architecture](docs/architecture.md), [runtime](docs/runtime.md), and [file storage](docs/storage.md) (Simplified Chinese).

## Recovery and Data Persistence

Sessions, message branches, run checkpoints, pending questions, and subtask state are stored in PostgreSQL. After an application process crashes and restarts, a background reconciler checks expired leases and takes over recoverable runs from safe checkpoints. Leases and monotonically increasing fencing tokens prevent stale executors from continuing to write run state.

| Interruption | Recovery behavior |
| --- | --- |
| Page refresh, SSE disconnect, or lost Redis events | Reconnection reads a database snapshot first, then resumes incremental events; committed session data is retained |
| Crash during model response generation | Retries the interrupted model turn from a safe checkpoint; unfinished drafts may be replaced, with no guarantee of word-for-word continuation |
| Restart while waiting for a user answer | Preserves the question and waiting state; the same run continues after the user answers |
| Restart while waiting for subtasks | Restores task state and resumes coordination; completed results are reused, and read-only subtasks with expired leases may rerun within their original deadlines |
| Crash during an ordinary tool batch | If the outcome of external operations is uncertain, marks the current run as failed and retains session history; does not automatically replay the batch, avoiding duplicate side effects |

**Retaining session data and automatically continuing the current run are separate guarantees.** Before retrying an interrupted ordinary tool, verify the outcome of its external operation. A failed run does not mean the external operation never happened.

Recovery requires intact PostgreSQL and attachment storage, with the restarted service connecting to the same persisted data. Continued execution also requires dependencies such as Redis and the model API to become available again. Use persistent storage for the database and attachments; multiple instances must share an attachment volume or S3-compatible bucket. Backups must cover both the database and attachments. Do not rely on an ephemeral container filesystem.

These mechanisms cover application process failures. Disasters such as database or disk corruption and host loss require deployment-specific backups, highly available storage, and recovery drills. The project does not guarantee zero data loss or a fixed recovery time under arbitrary failures.

See [agent runtime](docs/runtime.md) for checkpoint, lease, and tool failure semantics; [file storage](docs/storage.md) for persistence requirements; and [testing and verification](docs/verification.md) for documented recovery test coverage (Simplified Chinese).

## Development and Builds

```sh
make check   # Backend lint and tests; frontend lint and tests
make build   # TypeScript checks and frontend production build
```

After building, FastAPI can serve the frontend from the same origin:

```sh
cd server
CORNAGENT_SERVER_RELOAD=false uv run python -m app.serve
```

When upgrading an existing installation, stop the service before applying database migrations:

```sh
cd server
uv run alembic upgrade head
```

Regression tests against real PostgreSQL and Redis create and clean up their own random schema without clearing existing databases or Redis data:

```sh
cd server
CORNAGENT_TEST_POSTGRES_URL=postgresql+psycopg://localhost:5432/cornagent \
CORNAGENT_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run pytest -q
```

By default, the project listens locally, and all browsers share one workspace. When exposing the service externally, configure access controls in the host system. Built-in login and multi-tenant isolation are not currently provided.

## Documentation

The detailed guides below are currently available in **Simplified Chinese**.

| Guide | Contents |
| --- | --- |
| [Frontend](frontend/README.md) | Page organization, themes, localization, and message interactions |
| [Frontend integration](docs/frontend-integration.md) | Provider, launcher, sidebar, and host configuration |
| [Backend](server/README.md) | Service startup, dependencies, configuration, and checks |
| [Architecture](docs/architecture.md) | Module responsibilities and request flow |
| [Agent runtime](docs/runtime.md) | State machine, recovery, SSE, and message trees |
| [Subtasks and tools](docs/subagents.md) | Parallel tasks, tool extensions, and demos |
| [File storage](docs/storage.md) | Attachment reads and writes, session isolation, and cleanup |
| [Testing and verification](docs/verification.md) | Regression coverage and interface verification records |
| [Brand assets](assets/brand/README.md) | SVG icons, wordmarks, and usage |

## Contributing

Use issues to report bugs or discuss features, and pull requests to contribute improvements. Run `make check` and `make build` before submitting. Changes to the state machine, SSE, storage, or message branches should also verify refresh and recovery behavior. Do not commit secrets, user conversations, uploaded files, or runtime data.

When updating this README, keep the [Simplified Chinese version](README.zh-CN.md) in sync, including examples, links, and behavior descriptions.

## License

CornAgent is released under the **[MIT License](LICENSE)**. See [NOTICE](NOTICE) for attribution to source projects and third-party dependencies.
