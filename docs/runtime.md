# Agent 运行时

状态：active

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
同一公网出口的访问者共享配额。IP 仅用于限流，不提供登录或数据隔离。
配置 Redis 时以哈希键和原子计数跨实例共享配额；Redis 故障返回 503。未配置 Redis 时仅在单进程内计数。

运行器支持 provider retry、DeepSeek 503 fallback、上下文压缩、3 MiB checkpoint 限制、stream batching、并发控制与指标。
系统提示词独立在 `app/agent/prompt.py`，模型与所有预算由 `Settings` 配置。

## Root / Child 持久化边界

Root 新增 `waiting_for_subagents`，仍属于活跃运行，用户可以停止。等待与原始 assistant tool call continuation 同事务保存；恢复时按原 `tool_call_id` 添加标准 tool message、增加 epoch、回到 pending。等待用户与等待子任务都是释放租约和实例执行名额的暂停状态；Child 在 Root 等待用户时仍可完成，但不会代替用户回答唤醒 Root。

Child 状态为 `queued → running → completed / needs_input / failed / timed_out / cancelled`。任务表保存 Root、组、角色、required、原始定义、固定截止时间、独立租约/fence、执行次数、完整结果、完成序号和交付状态。所有事务遵守 Root → Child 锁顺序；稳定工具调用标识和唯一约束防止重复派发。结果与 Root checkpoint 的交付标记同事务提交。

Child 租约过期可在原截止时间内重新执行只读任务；旧 fence、过期租约或 Root cancel epoch 不匹配的结果被拒绝。Root 取消、失败、完成或会话删除会终止剩余任务；可选任务不会阻止最终回答，Root 完成时取消剩余可选任务。完成结果不重新运行。

Root 从安全 checkpoint 回退半个模型轮次时，按任务标识重新合并数据库最新任务投影。完整结果入库不依赖 Root 草稿的剩余空间；后续交付若无法经历史压缩放入 checkpoint，将明确失败。详情见 [结果预算与工具协议](subagents.md)。

## 最终回答与事件一致性

模型轮次开始时若有必需任务未终态或未收取，先缓冲该轮正文/思考。模型选择继续使用工具时释放过程输出；模型试图直接结束时丢弃候选回答，先收取已完成结果或注册等待，再重新调用模型。Child 在生成期间刚好完成也不能使未经收取的候选答案直接提交。事务内再次验证所有必需任务已经终态且交付。

接收 Redis 事件时若 epoch 改变或 sequence 不连续，服务端先发送权威 PostgreSQL snapshot，再从快照游标继续。终态事件同样以终态快照收口，避免跨执行器乱序或发布失败遗漏任务投影。快照按稳定部件标识整体替换，历史刷新、SSE 重连和侧边栏使用相同类型与渲染路径。
