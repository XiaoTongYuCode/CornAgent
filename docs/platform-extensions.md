# Runtime 扩展、MCP 与评测

状态：active

## 持久化边界

`server/app/persistence/checkpoints.py` 集中管理 checkpoint 的大小与普通工具批次的重放标记；
`transitions.py` 定义 Run 可接受的状态转换。所有转换在持有 Run 行锁的事务内执行，仍由
PostgreSQL 租约、单调 fence、回执和 checkpoint 共同决定是否能恢复。不能单凭一个状态枚举
推断外部操作未发生。

`DurableBackend.transact(operation)` 是运行器提交同步 Repository 操作的注入边界；
默认 `PostgresDurableBackend` 为每次操作单独创建 Session，并保留现有原子提交语义。
宿主可通过 `create_app(durable_backend=...)` 注入适配器，但适配器必须实现相同的
`AgentRepository` 事务、行锁、fence 和回执契约。HTTP 会话入口、子任务 Repository
及关系模型仍以 PostgreSQL 为事实源；目前**不支持**把运行状态直接移到 Temporal、
DBOS 或其他存储引擎，也不承诺更换数据库即可运行。

审批写工具可使用 `ToolDefinition.approved(name=..., description=..., parameters=...,
prepare=..., execute=...)` 注册。prepare 只读并返回 `ToolApproval`；execute 用
`context.operation_id`（稳定的 Run ID 与 tool-call ID）向业务系统提交幂等操作。
相同操作可能在重启后再次调用 execute，因此宿主需要持久化幂等记录或版本校验。
没有远端幂等保证时，显式设置 `approval_replay_safe=False`：仍要求用户审批，但最多执行
一次，不处理 `retryable` 重试；执行前持久化禁止重放标记，执行结果、回执、标记完成和
审批清理在同一事务提交。标记已开始而结果未提交时，恢复以
`agent_tool_batch_indeterminate` 失败，需人工核实远端，不代表远端未执行。

## MCP 工具

设置 `CORNAGENT_AGENT_MCP_SERVERS` 为 JSON 数组。示例：

```json
[
  {
    "name": "catalog",
    "url": "https://mcp.example.com/mcp",
    "tools": ["search", "update"],
    "read_only_tools": ["search"],
    "write_tools": ["update"]
  }
]
```

服务启动时从配置的 Streamable HTTP MCP server 发现 schema，逐项核对允许的工具；
缺失工具导致启动失败。模型只会发现服务端白名单中的工具，名称为
`mcp_catalog_search` 等。所有工具默认只向 Root 开放，需要经 `search_tools` 加载；
每个工具必须明确归入只读或写工具。将写工具标成只读会允许其在只读恢复路径重试，
必须由管理员严格核验。写工具独占工具轮次，先展示服务器、工具、目标地址及完整参数，
用户明确选择确认后才调用远端；拒绝、忽略或自由文本均不批准写操作。
审批绑定目标地址与工具名，重启后配置改变会拒绝执行原计划。
MCP 不具备统一的远端幂等契约，固定使用 `approval_replay_safe=False`，超时、未知结果及
执行中崩溃不会自动重试或重放；调用开始前崩溃可恢复等待或已批准的计划。
即使远端返回成功文本也不推断有业务已提交回执。MCP 暂不传递用户
身份和鉴权令牌，远端服务应由部署者控制访问。HTTP URL 要求 HTTPS，本机回环
地址可使用 HTTP。图片与二进制返回不写入回执，文本和结构化结果有长度限制。

## 可观测与评测

已有的 `/metrics`、`/agent/usage` 和模型请求诊断继续可用。可设置
`CORNAGENT_OTLP_TRACES_ENDPOINT`（完整 `/v1/traces` 地址）发送 Run/Tool
span；默认关闭。Span 只记录运行 ID、工具名称及状态，不记录提示词、工具参数
或工具结果。
宿主已有 OpenTelemetry SDK `TracerProvider` 时在该 provider 上添加一个导出 processor，
保留宿主 resource 和已有 processor；CornAgent processor 仅接收 `cornagent.agent` scope
下的 `agent.run` / `agent.tool`，不会将宿主其他 tracing 内容发往该 OTLP 目标。
重复使用同一配置不重复添加。宿主 provider 不兼容、
全局安装被拒绝或重复初始化改变 endpoint 时明确失败，不把未生效的配置标成成功。

在 `server` 目录运行：

```sh
uv run python -m app.platform_cli inspect --limit 20
uv run python -m app.platform_cli eval evals/smoke.json --report eval-report.json
```

`inspect` 从持久数据库读取近期 Run 状态、过期租约和活跃子任务；`--limit` 只限制近期 Run，
过期运行租约独立查询，不因创建时间较旧而遗漏。需要部署
环境的数据库连接权限。它是本机操作入口，不开放新的管理员 HTTP API。
`eval` 创建真实会话，等待终态，检查期望字符串并生成 JSON 结果；默认在完成
后删除测试会话，可用 `--keep-sessions` 保留。它会调用模型与配置的工具，
所以请在隔离的环境中使用只读评测工具。开启用户系统时可用
`CORNAGENT_EVAL_COOKIE` 环境变量提供已有登录 Cookie。
这是最小端到端回归集，不是模型能力的统计评测或质量评分体系。
