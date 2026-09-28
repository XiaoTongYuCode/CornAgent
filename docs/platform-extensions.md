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
必须由管理员严格核验。写工具遵循普通工具的未知副作用规则：执行中崩溃不会自动重放，
即使远端返回成功文本也不推断有已提交回执。MCP 暂不传递用户
身份和鉴权令牌，远端服务应由部署者控制访问。HTTP URL 要求 HTTPS，本机回环
地址可使用 HTTP。图片与二进制返回不写入回执，文本和结构化结果有长度限制。

## 可观测与评测

已有的 `/metrics`、`/agent/usage` 和模型请求诊断继续可用。可设置
`CORNAGENT_OTLP_TRACES_ENDPOINT`（完整 `/v1/traces` 地址）发送 Run/Tool
span；默认关闭。Span 只记录运行 ID、工具名称及状态，不记录提示词、工具参数
或工具结果。

在 `server` 目录运行：

```sh
uv run python -m app.platform_cli inspect --limit 20
uv run python -m app.platform_cli eval evals/smoke.json --report eval-report.json
```

`inspect` 从持久数据库读取近期 Run 状态、过期租约和活跃子任务；需要部署
环境的数据库连接权限。它是本机操作入口，不开放新的管理员 HTTP API。
`eval` 创建真实会话，等待终态，检查期望字符串并生成 JSON 结果；默认在完成
后删除测试会话，可用 `--keep-sessions` 保留。它会调用模型与配置的工具，
所以请在隔离的环境中使用只读评测工具。开启用户系统时可用
`CORNAGENT_EVAL_COOKIE` 环境变量提供已有登录 Cookie。
这是最小端到端回归集，不是模型能力的统计评测或质量评分体系。
