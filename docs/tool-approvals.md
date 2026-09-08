# 工具审批接入

状态：active

目的：让可产生外部修改的扩展工具通过服务端计划、明确用户决定和持久化恢复执行。

注册 `ToolDefinition(handler=prepare, approval_handler=execute)` 即启用独占审批工具。
`prepare` 只能读取和校验；返回普通失败结果，或包含可读计划与私有参数的 `ToolApproval`。

```python
from app.agent.tools import ToolApproval, ToolDefinition

async def prepare(arguments, context):
    plan = await service.prepare_change(arguments, context)
    return ToolApproval(
        query=plan.description,
        payload=plan.resume_payload,
        approve_label="应用变更",
        cancel_label="取消",
    )

async def execute(payload, context):
    # 服务端重新检查目标、权限、版本；以 Run + tool-call ID 幂等执行。
    # 影响用户决定的内容若变化，返回新的 ToolApproval。
    return await service.apply_change(
        payload, context,
        idempotency_key=f"{context.run_id}:{context.tool_call_id}",
    )

tool = ToolDefinition(
    name="apply_change",
    description="Apply the user's requested change after reviewing its plan.",
    parameters={"type": "object", "properties": {"target": {"type": "string"}},
                "required": ["target"], "additionalProperties": False},
    handler=prepare,
    approval_handler=execute,
    status_label="正在应用变更",
)
```

示例中的 `service` 由宿主实现；将 `tool` 传入 `create_app(additional_tools=(tool,))`。
无需新增模型可见的“审批工具”。该能力只向 Root 开放，不能设为 Child 工具或私有结果工具。
普通 `ask_user` 用于澄清信息，不构成对某个工具计划的批准。

- 用户只提交问题 ID 与明确选项，不能用自由文本批准；重复响应复用 API 幂等键，冲突响应拒绝。
- `execute` 必须保证相同 payload 可安全重放，不能仅依赖进程内变量判重。异常响应后仍可能已经写入，
  因而需要持久化幂等记录、可查询操作回执或目标版本校验。
- 可重试失败返回 `retryable=true`，运行时单次恢复最多执行三次；取消不调用 `execute`。
- 结果必须可 JSON 序列化且有界。私有计划只存于服务端；不要把密钥或无关数据放进 payload。
- 运行时保留原始 tool-call ID，批准后无需模型重新生成调用。结果和 checkpoint 清理原子提交，
  进程崩溃后恢复原操作；普通工具未知副作用批次仍以失败结束。

升级与状态机见 [运行时](runtime.md)。回归覆盖批准、拒绝、忽略、重启、写入后崩溃、瞬时错误、
计划变化、自由文本拒绝及重复回答。
