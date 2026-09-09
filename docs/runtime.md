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
