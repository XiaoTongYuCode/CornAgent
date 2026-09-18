# Agent 运行时

状态：active

HTTP 写入口的同步 Repository 操作在线程池内执行，每个数据库阶段独立创建并关闭 Session。
幂等预检结束后释放连接，再等待 Redis 准入或来源解析；提交阶段重新校验状态与幂等键。
提问响应遵循 Run → Question 的锁顺序，并在取得锁后刷新 ORM 缓存，避免回答与取消竞争时使用旧状态。

业务来源只在创建会话时由服务端解析，保存为首条用户消息的历史背景快照；不作为每轮系统消息重复注入。
编辑首条消息保留该快照，重新生成和重启恢复沿用历史与检查点；上下文压缩后不重新追加旧来源。
来源表示会话开始时的状态，需要最新信息时应由工具重新读取。同步来源解析器在线程池执行。
升级已有安装时先停止服务，再运行 `uv run alembic upgrade head`（在 `server` 目录）；
`0003_source_history` 将已有来源补入首条消息各版本与现有恢复检查点，避免旧会话丢失背景。

`app/persistence/agent_runtime.py` 拥有事务、消息树、checkpoint 与租约状态；`app/agent/runtime.py` 组合 provider、工具和 Redis。

```text
pending → running → completed / failed / cancelled
             ↓
       waiting_for_user / waiting_for_subagents → pending
```

30 秒租约、10 秒续租和单调 fence；reconciler 从安全 checkpoint 接管过期运行。
模型半轮中断后增加 epoch，通过数据库 snapshot 替换旧草稿。普通工具批次标记为 executing 后若中断，将运行标记为失败，避免重复执行外部副作用。

`ask_user` 必须独占工具轮次。问题、canonical options、tool_call_id 与 continuation 同事务入库后释放租约。
回答/忽略按原始 tool_call_id 形成标准 tool message，原 Run 回到 pending、epoch 增加。问题没有自动超时。
五个子任务编排工具同样独占工具轮次。模型把独占工具与其他工具混入同一批次时，
运行时不会执行其中任何工具，而是持久化标准失败 tool result 并允许模型纠正一次；
同一 Run 再次返回非法独占批次时以 `invalid_agent_tool_batch` 失败，避免无限重试或重复副作用。

SSE 事件格式：

```text
id: <epoch>:<sequence>
event: snapshot | session | delta | reasoning_delta | tool_call | user_question | done | error | cancelled
data: <json>
```

首次连接始终先发 PostgreSQL snapshot (`replace=true`)，然后接 Redis 增量；客户端游标不能越过数据库事实。
事件先提交数据库，再发布 Redis。Redis 丢失、发布失败或裁剪不丢会话事实。XADD、MAXLEN 和 TTL 同事务。

Message 使用 parent_message_id、version_group_id、supersedes_message_id 保存分支，active_leaf_message_id 决定当前可见链。
前端 `src/agent` 处理请求代次隔离、流重连、消息合并、历史分页、问题 upsert 和统一 Markdown/过程区渲染。
后端 API 提供编辑消息入口，聊天界面支持重新生成与相邻版本切换。

所有可变运行操作要求 Idempotency-Key；新会话首次提交为原子事务，一个 Session 同时最多一个活跃 Run。
停止生成与忽略问题不同：前者取消整个 Run，后者继续当前 Run。

## 新 Run 的 IP 限流

没有账户系统时，仅在新 Run 准入检查中使用客户端 IP 作为 user 标识；数据库、历史记录和 SSE 仍使用固定共享工作区。
新建会话、发送消息、重新生成和编辑消息共享每 IP 默认 **6 次/60 秒** 的配额（`CORNAGENT_AGENT_USER_RUNS_PER_MINUTE`）。
窗口从首次准入请求开始计时，60 秒后重置；超额返回 HTTP 429、`agent_run_rate_limited` 和 `retry_after_seconds`。
幂等重放不重复扣配额；回答或忽略提问恢复原 Run，不消耗新 Run 配额。通过幂等预检后的新 Run 尝试会计数，即使后续创建失败。
共享 tenant 仍有默认 60 次/60 秒的全站上限，实例执行并发与 SSE 连接上限维持原配置。

IP 来自 ASGI `request.client`，应用不自行信任 `X-Forwarded-For`、`X-Real-IP` 等请求头。
由 ASGI 服务配置可信代理并解析客户端地址；IPv6 规范化，IPv4 映射地址归入对应 IPv4 配额，缺失或非法地址归入统一受限桶。
上述规则适用于用户系统关闭时：同一公网出口的访问者共享配额，IP 仅用于限流，不提供登录或数据隔离。

开启[用户系统](authentication.md)后，新 Run 按鉴权后的用户身份计数，每用户仍默认 6 次/60 秒；无感模式使用 IP＋浏览器 Cookie，账号模式使用稳定账号 ID。内置适配器为每个用户分配独立 tenant，因此 tenant 配额也按该用户作用域计算，不再是全站总额；实例执行并发限制仍适用。
配置 Redis 时以哈希键和原子计数跨实例共享配额；Redis 故障返回 503。未配置 Redis 时仅在单进程内计数。

运行器支持 provider retry、DeepSeek 503 fallback、上下文压缩、3 MiB checkpoint 限制、stream batching、并发控制与指标。
系统提示词独立在 `app/agent/prompt.py`，模型与所有预算由 `Settings` 配置。
默认直接处理问候、问答与简单任务；必要时才检索、澄清或拆分独立只读工作，
子任务指令由主 Agent 编写。每轮编排提醒和工具说明遵循同一按需原则，
不要求用户填写工具参数。修改提示词后需重启服务；历史回复不会被改写。

## Root / Child 持久化边界

Root 新增 `waiting_for_subagents`，仍属于活跃运行，用户可以停止。等待与原始 assistant tool call continuation 同事务保存；恢复时按原 `tool_call_id` 添加标准 tool message、增加 epoch、回到 pending。等待用户与等待子任务都是释放租约和实例执行名额的暂停状态；Child 在 Root 等待用户时仍可完成，但不会代替用户回答唤醒 Root。

Child 状态为 `queued → running → completed / needs_input / failed / timed_out / cancelled`。任务表保存 Root、组、角色、required、原始定义、固定截止时间、独立租约/fence、执行次数、完整结果、完成序号和交付状态。所有事务遵守 Root → Child 锁顺序；稳定工具调用标识和唯一约束防止重复派发。结果与 Root checkpoint 的交付标记同事务提交。

Child 租约过期可在原截止时间内重新执行只读任务；旧 fence、过期租约或 Root cancel epoch 不匹配的结果被拒绝。Root 取消、失败、完成或会话删除会终止剩余任务；可选任务不会阻止最终回答，Root 完成时取消剩余可选任务。完成结果不重新运行。

Root 从安全 checkpoint 回退半个模型轮次时，按任务标识重新合并数据库最新任务投影。完整结果入库不依赖 Root 草稿的剩余空间；后续交付若无法经历史压缩放入 checkpoint，将明确失败。详情见 [结果预算与工具协议](subagents.md)。

## 最终回答与事件一致性

模型轮次开始时若有必需任务未终态或未收取，先缓冲该轮正文/思考。模型选择继续使用工具时释放过程输出；模型试图直接结束时丢弃候选回答，先收取已完成结果或注册等待，再重新调用模型。Child 在生成期间刚好完成也不能使未经收取的候选答案直接提交。事务内再次验证所有必需任务已经终态且交付。

接收 Redis 事件时若 epoch 改变或 sequence 不连续，服务端先发送权威 PostgreSQL snapshot，再从快照游标继续。终态事件同样以终态快照收口，避免跨执行器乱序或发布失败遗漏任务投影。快照按稳定部件标识整体替换，历史刷新、SSE 重连和侧边栏使用相同类型与渲染路径。

## 工具并发与审批恢复

`CORNAGENT_AGENT_TOOL_MAX_CONCURRENCY` 默认 4，按进程在 Root、Child 和审批执行间共享。
它独立于 Run 并发上限；排队期间取消的调用不启动 handler。调用者被取消但底层线程还在运行时，
名额保留到 handler 真正退出；工具实现仍须设置外部 IO 超时并遵守取消上下文。

带 `approval_handler` 的工具先执行只读准备，返回服务端 `ToolApproval`，再暂停到 `waiting_for_user`。
Question 与 checkpoint 保存同一计划、原 tool-call ID 和用户决定；私有 payload 不进入公共消息或 SSE。
用户选项和待执行决定在同一事务提交，恢复时先执行该操作，再请求模型，取消不执行操作。
计划变化时重新询问，仍使用原 tool-call ID；瞬时错误最多尝试三次。只有保证同一 payload
可幂等重放的 handler 才能注册审批恢复；普通工具的未知副作用批次仍禁止自动重放。

升级前停止服务，执行 `uv run alembic upgrade head` 应用 `0004_tool_approvals`，再启动前后端。
该迁移保留普通 ask_user 的调用唯一性，允许同一业务调用因计划变化产生多次审批。
扩展契约与示例见 [工具审批](tool-approvals.md)。

模型参数不被 LiteLLM 支持时，Run 使用 `agent_model_configuration_error` 明确失败；不当作瞬时故障重试。
可选 `CORNAGENT_AGENT_REASONING_EFFORT` 同时用于主模型和子模型，留空保持模型默认值。
DeepSeek 的推理参数通过单次请求白名单透传；其他模型按提供商支持情况验证，不设置全局参数丢弃。

## 排队消息与引导消息

运行期间输入框保持可用：Enter 排队，Ctrl+Enter 引导；空输入框保留停止按钮，按 Enter 不会停止运行。
队列组件支持编辑、删除、重试、切换排队/引导。共享工作区、聊天页与侧栏共用接口。

`POST /agent/sessions/:id/inputs` 保存 `queue` 或 `steer`，`POST /agent/inputs/:id` 携带 `version` 修改。
两者要求 Idempotency-Key，服务端校验归属；新输入沿用用户/tenant 新 Run 准入配额，幂等重放不重复扣配额。
每个会话最多 20 条 pending/failed 输入。文件提交时即认领到会话，避免未执行前被临时上传清理器删除。
取消队列项不删除已认领附件，会话删除时统一回收。

- queue：会话没有活跃 Run 时按提交顺序创建下一 Run，队列状态与 Run 在同一事务提交。
- steer：不打断正在进行的模型流或工具；在下一模型边界插入用户消息，与 safe checkpoint 同事务提交。
  最终回答提交前再次检查，避免边界竞争吞掉引导消息；active assistant 顺序移动到引导用户消息之后。
- 等待问题时，引导消息取消当前问题再恢复原 Run；这不代表批准任何工具。等待子任务时仍等待原安全边界。
- pending 输入在服务重启后由 reconciler 继续派发；已 applied 不重复执行。不可认领的输入标为 failed，支持修正后重试。
- `input_queued` / `input_applied` 触发前端读取权威会话；快照重连与有界后台同步处理漏事件及新 Run 交接。

升级前停止服务，执行 `cd server && uv run alembic upgrade head`，应用 `0007_agent_inputs` 后再启动。

## 模型窗口与滚动压缩

输入阈值为 `floor(context_window_tokens * 0.8) - output_max_tokens`，包含系统提示、工具 schema、
运行提示与物化后的文件读取内容；输出预留同时作为 provider 请求的 `max_tokens`。
`CORNAGENT_AGENT_CONTEXT_WINDOW_TOKENS` 和 `CORNAGENT_AGENT_FALLBACK_CONTEXT_WINDOW_TOKENS`
可显式声明部署容量；启用 fallback 时采用两者较小值。未声明时，按官方部署白名单识别容量，
其他模型或代理保守采用 64,000；实验模型名不推断为正式模型容量。没有调用远端接口探测上下文上限。
子任务继承输出预留，窗口不超过主任务；单独指定的子模型再采用其部署窗口的较小值，
并把子任务系统提示和工具 schema 纳入预算、按实际 token 用量校准。

每轮实际 `prompt_tokens` / `input_tokens` 与请求估算比值乘 1.1，限制在 0.5–4，写入工具上下文 checkpoint。
字节上限独立防止存储膨胀：`min(32 MiB, max(3 MiB, window * 16 + 256 KiB))`，为工具结果保留空间。
触发压缩后以剩余历史预算的 60% 为目标，避免下一条消息马上重新触发。

压缩完整的已完成消息单元，尽量保留最近两轮；同一条用户指令内连续工具读取也可压缩。
当前用户指令、用户附件原始引用、写工具/交互回执、未完成调用不交给摘要模型改写。
私有文件读取先重新鉴权、物化文本供摘要模型阅读，摘要只保留事实和服务端维护的文件读取引用，
不把原文、图片 base64 或存储路径写入 checkpoint。再次压缩保留这些服务端引用。
摘要过长时最多再压缩三次；摘要请求超窗递归分段，主调用超窗只在没有开始输出时安全重试一次。
无法缩小、最新输入本身过大或受保护证据无法容纳时明确失败，历史与已完成回执仍保留。
界面通过同一工具过程通道显示整理中、已整理或失败，刷新后由持久状态恢复。

## 按需工具与技能

默认模型适配器只在请求中挂载基础工具：`search_tools`、`read_skill`、`ask_user`、`read_file`、
`read_tool_result`、`list_materials`、`search_materials` 和 `read_material`。实际挂载仍取决于注册和
当前 Root/Child 作用域；例如 Child 不会获得 `ask_user` 或有副作用的业务工具。
网页工具、子任务编排和应用注入的普通工具先通过 `search_tools(query, max_results)` 搜索并加载。
搜索支持工具名、中英文关键词和 `*` 目录浏览，每次最多 8 项；匹配结果中的工具 schema 从下一轮请求生效。

`read_skill(name)` 只读取服务端 `AgentSkillCatalog` 注册的指南，不能访问任意文件路径。
技能可声明说明、关键词、`required_tools`、`execution_scopes` 和 `required_flags`；只有当前范围内
所有所需工具均注册、所需服务端功能开关均为布尔值 `True` 时才能发现和加载。功能开关来自
`ToolExecutionContext.extra["feature_flags"]`，不接受用户、模型或工具结果设置。
读取指南同时加载其声明的工具，后续请求只注入已加载且仍适用的指南正文。

工具定义的 `resident=True` 可将应用工具设为常驻；`group`、`keywords` 用于能力搜索。
`effect="read" | "write" | "control"` 声明工具的操作性质，`outcome_projector` 可从实际执行结果
生成结构化事实回执。`read_only` 和 `execution_scopes` 继续控制 Child 的执行范围；
加载工具本身不会授予身份权限，也不会替代业务 handler 的授权检查。

加载集合保存于 Run 的 `tool_context_state.tool_loading`，在暂停、恢复和上下文压缩后保留。
每个 Run 独立持有集合，新 Run 只继承有效消息分支上最近祖先回复的受信加载状态；
编辑或切换到不含该祖先的分支时，不带入其他分支的加载集合。
部署移除的工具和当前作用域无权使用的工具会重新过滤。
用户文字、普通工具结果和摘要里的 `loaded_tools` 不会改变挂载集合。
每轮请求前固定本轮工具名集合；模型在同一批中调用 `search_tools` 和刚发现的工具，后者仍会被拒绝。
审批等独占运行时工具也检查本轮集合，不能绕过普通执行器的加载限制。
服务端为恢复既有私有资料进行的回读不属于新的模型调用，但仍执行身份与会话归属检查。
`private_result` 工具必须声明 `read_only=True` 且不能声明 `effect="write"`，因为这些读取会重新执行；
被拒绝或失败的调用保存安全错误结果，不生成可在后续模型请求中执行的私有读取引用。

模型适配器实现 `stream_with_tools(messages, *, tools)` 即启用动态工具协议。
LiteLLM 的主请求、重试及 fallback 都使用该次请求的工具快照，不修改共享模型实例的默认 `tools`，
因此并发 Run 不会互相添加工具。仅实现旧 `stream(messages)` 的自定义适配器继续接收全量 catalog，
保持旧接口兼容；接入方需实现新方法才能获得按需加载行为。两种接口均保留作用域与业务授权限制。
