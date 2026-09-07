# 子任务与工具扩展

状态：active

主 Agent（Root）可以派发多个只读子 Agent（Child），继续处理自己的工作，再等待和收取结构化结果。每个子任务拥有独立上下文与工具状态；PostgreSQL 保存任务定义和完整结果。聊天页与侧边栏展示相同的任务分组、标题、可展开摘要和错误；子任务标题旁不显示状态标记，也不显示角色、必需标记、任务组、耗时和交付详情行。

## 五个编排工具

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| `spawn_subagents` | `tasks`, 可选 `max_concurrency` | 原子创建任务，立即返回 `group_id` 与任务标识，Root 继续执行 |
| `list_subagents` | 可选 `group_id`、`task_ids` | 查询状态和简短预览，不收取完整结果 |
| `collect_subagent_results` | 可选 `group_id`、`task_ids` | 按完成序号收取尚未交付的完整结果，不等待 |
| `wait_subagents` | `task_ids`，可选 `group_id`、`return_when`、`timeout_seconds` | `any/all` 条件不满足时持久化暂停；满足或等待到期后收取就绪结果并恢复 |
| `delegate_tasks` | `tasks`，可选 `max_concurrency`、`timeout_seconds` | 创建任务并等待全部终态，等价于 spawn 后 wait all |

五个工具与 `ask_user` 均独占工具轮次。每个任务包含 `title`、`instruction`、`expected_output`，可选 `profile`（researcher / analyst / verifier）与 `required`（默认 true）。任务键由服务端根据稳定工具调用标识和序号生成。`instruction` 应自包含，Child 不继承 Root 的对话、附件或业务权限。

等待条件只看任务是否终态。`pending_task_ids` 表示未完成任务，`undelivered_result_task_ids` 表示已完成但尚未交付的结果；Root 按 `next_action` 选择继续 collect 或 wait。等待超时不会取消 Child。`required=true` 的任务必须进入终态并收取结果才能结束 Root，包括 failed、needs_input、timed_out、cancelled 结果；Root 负责解释失败或调用 `ask_user` 请求必要输入。

Child 最终返回 JSON：

```json
{
  "status": "completed",
  "summary": "模拟资料显示模块化方案便于维护，接口兼容性仍需核验。",
  "evidence": [{"claim": "接口兼容性待验证", "source_title": "[模拟] 集成风险", "url": "https://example.com/cornagent-demo/integration-risk"}],
  "warnings": ["缺少真实成本数据"]
}
```

Child 可生成 `completed` 或 `needs_input`；运行时生成失败、取消和超时结果，并附加模型名、用量与完成序号。终态结果不可被旧执行器覆盖。

## 默认配置

完整配置名见根目录 [.env.example](../.env.example)。

| 配置 | 默认值 |
| --- | --- |
| 开启子任务、模拟工具 | 子任务 true，模拟工具 false |
| 单次 / 每 Root 任务数 | 10 / 10 |
| 每 Root Child 并行 / 每实例 Root + Child 执行数 | 5 / 20 |
| Child 截止时间 | 从创建起 600 秒，重试不延长 |
| 等待默认 / 最大 | 300 / 600 秒 |
| Child 租约 / 续租 / 协调间隔 | 30 / 10 / 1 秒 |
| 结果分批目标 | 64 KiB，单个结果保持完整 |
| 界面摘要投影 | 最多 8000 字符，不影响完整结果 |
| checkpoint 硬限制 | 3 MiB |
| 必需任务存在时，单个候选回答缓冲上限 | 256 KiB，超限明确失败 |

`CORNAGENT_AGENT_SUBAGENT_MODEL` 留空时使用主模型名称，连接、凭据、重试与备用模型配置复用服务端配置。关闭 `CORNAGENT_AGENT_SUBAGENTS_ENABLED` 只拒绝新派发；运行器继续调度、恢复、交付和取消已存在的任务。

64 KiB 是分批目标，首个单独结果可以超过目标。交付写入 Root checkpoint 与任务交付标记处于同一事务；空间不足时只压缩已闭合历史，再尝试完整交付。仍无法放入 3 MiB 时明确失败，保留 Child 原结果，不能截断结果后标记已交付。界面截断只影响展示。

## 直接演示

配置模型与本机 PostgreSQL/Redis，运行 `make setup && make dev`，在 `/chat` 或 `/sidebar` 发送：

先显式设置 `CORNAGENT_AGENT_MOCK_TOOLS_ENABLED=true`，仅用于以下模拟演示。

> 演示并行子任务。先由你调用 mock_web_search 搜索“电池方案”，再使用 spawn_subagents 同时派发三个 required=true 的任务：researcher 收集晨光模块化方案的优势；analyst 比较晨光与松林方案；verifier 核验接口风险和证据缺口。每个任务应调用 mock_web_search，并在结果中明确写出“模拟资料”。派发后你继续搜索成本缺口，调用 list_subagents 查看进度，然后 wait_subagents 等待，并 collect_subagent_results 收齐未交付结果，最后生成一份带证据和未知项的对比表。所有资料均为本地虚构示例，不要称为真实网络搜索。

快捷等待模式可将派发要求改为 `delegate_tasks`。正式应用中的 Root 和 Child 都使用真实模型；默认网络工具使用真实 Tavily/Jina 数据，以上演示显式使用模拟资料。真实模型自行选择工具，因此确定性验收另使用测试模型。

不依赖模型密钥的浏览器演示入口是 `tests.subagent_browser_app:browser_app`：显式注入两个测试模型，实际经过编排、工具执行、数据库、Redis 和前端渲染。先准备专用空测试 schema，将它写进 `CORNAGENT_DATABASE_URL` 的 `options=-csearch_path%3D<schema>`，运行迁移；然后从 `server` 启动：

```sh
# 使用专用测试数据库/schema URL，禁止复用正式数据。
CORNAGENT_DATABASE_URL="$CORNAGENT_DEMO_DATABASE_URL" uv run alembic upgrade head
uv run uvicorn tests.subagent_browser_app:browser_app --factory --host 127.0.0.1 --port 18100
```

先在根目录执行 `make build`，打开 `http://127.0.0.1:18100/chat`，发送任意演示文字。测试 Child 故意等待数秒，方便查看等待、刷新和停止。这个入口不被 `make dev` 或 `app.main` 引用，回答明确标注固定测试模型。

## 挂载额外只读工具

普通工具默认仅开放给 Root。宿主显式声明 `execution_scopes` 与 `read_only` 后，同一个定义才能同时挂载到 Root 和 Child。目录构建和执行时均校验权限；Child 无法递归派发，也不能调用 `ask_user` 或默认 Root-only 的 `read_file`。

例如在 `server/example_app.py` 中注册宿主工具：

```python
from pydantic import BaseModel, ConfigDict
from app.agent.tools import ToolDefinition, ToolExecutionContext
from app.main import create_app
from app.settings import Settings

class LookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str

async def lookup(arguments: dict, context: ToolExecutionContext) -> dict:
    context.raise_if_cancelled()
    # 替换为宿主的只读资料访问；使用 context 中的身份/会话限定读取范围。
    return {"key": arguments["key"], "text": "宿主演示资料", "is_mock": True}

def app():
    tool = ToolDefinition(
        name="lookup_reference",
        description="读取宿主提供的固定演示资料，必须标注模拟资料。",
        parameters=LookupArguments.model_json_schema(),
        arguments_model=LookupArguments,
        handler=lookup,
        read_only=True,
        execution_scopes=frozenset({"root", "child"}),
    )
    return create_app(
        Settings(agent_mock_tools_enabled=False),
        additional_tools=(tool,),
    )
```

使用 `uv run uvicorn example_app:app --factory`。默认已注册 `web_search` 和 `read_url`，可用同一机制添加其他检索工具。工具名不能重复；如果要替换 `mock_web_search`，必须关闭默认注册。`read_only` 是宿主对代码行为的声明，宿主应确保访问凭据与处理函数确实只读；框架不对任意 Python 函数做系统调用沙箱。

自定义模型实现 `AgentModelClient.stream(messages)` 与 `compact(messages, max_tokens=...)`。`create_app(model_client=root_model, child_model_client=child_model)` 分别注入两个客户端，测试无需影响正式模型配置。Child 客户端接收独立系统提示和任务消息；使用自建 provider 适配器时也应绑定 Child 工具目录；直接注入 `LiteLLMAgentModel` 时设置 `system_prompt=None`，由 Child runner 提供独立提示词，避免附带主 Agent 的 Markdown/提问约定。工具上下文的 `checkpoint_state` 和 `runtime_cache` 在单个 Child 内共享，不与 Root 或兄弟任务共享；执行器丢失后 Child 从任务定义重新只读执行。

运行时专用 handler 返回 `RuntimeToolOutcome("continue", provider_messages)`、`RuntimeToolOutcome("waiting_for_user")` 或 `RuntimeToolOutcome("waiting_for_subagents")`，由持久化事务决定下一状态，不能再用 `None` 表示暂停。

## 可观测性

`/metrics` 提供 Child 活跃数、尝试数、完成状态、编排操作及其结果、工具/provider 调用、等待恢复数、协调恢复次数，以及 `cornagent_subagent_attempt_seconds_sum/count`。数据库任务投影另提供从首次执行到终态的耗时、尝试次数、交付状态与稳定错误码。指标使用操作/状态标签，不以任务标识生成高基数标签；完整结果保存在 PostgreSQL。

## 移植来源

固定归档提交：`1c934f0d6ed2970f7a36eac463ab08897f071523`。

| EigenLogic 来源（相对仓库路径） | CornAgent 落点与处理 |
| --- | --- |
| `app/business-agent/agent_server/app/llm/subagents/{protocol,tools,runner}.py` | `server/app/agent/subagents/`，复制协议校验与提示语义，改用现有模型和工具接口 |
| `app/business-agent/agent_server/app/services/agent/subagent_runtime.py` | Child 调度、Root 等待和最终回答检查，适配 CornAgent checkpoint/租约事务 |
| `app/business-agent/agent_server/app/storage/{models/agent_subagent_task,repositories/agent_subagent_task_repository}.py` | `server/app/persistence/subagents.py` 与 `0002_subagents`，整合 Root 锁、完成序号和交付事务 |
| `app/business-agent/agent_server/tests/test_subagent_*.py`、`test_agent_subagent_*.py` | `server/tests/test_subagents.py`、`test_subagent_migrations.py`，移植语义并增加双实例、SSE、完整交付回归 |
| `app/business-agent/agent_web/src/utils/{subagentIconColor,messageRenderPlan}.ts` 及任务标题/图标组件 | `frontend/src/agent/chat/`，复制稳定配色与分组规则，适配当前主题、字典和 tool_call 部件 |

未带入业务工具、业务鉴权或 EigenLogic 的部署与共享包依赖。与旧版内部实现的主要区别是复用 CornAgent 自有事务、模型、会话、SSE 及统一 React 工作区；本次对齐的是通用子任务编排能力。
