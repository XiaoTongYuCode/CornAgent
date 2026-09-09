# 使用统计与可插拔埋点

状态：active

`/usage` 使用 Bklit UI 的面积图、堆叠柱图、环图、热力图、图例、坐标轴与提示组件。日期选择使用 34px 高的 Ant Design `Segmented`。支持近 7 / 30 / 90 天、中英文、深浅主题、窄屏与减少动态效果。页面按需加载，与聊天共用 Provider；导航不重建工作区。

## 数据口径

`GET /api/v1/agent/usage?days=30` 使用服务端当前身份，按 tenant 与 membership 双重过滤；客户端不能指定查询用户。用户系统关闭时仍为共享工作区。没有跨用户管理面板，也没有通过此接口暴露全站用户数量。

- 时间：UTC 自所选首日零时至查询时刻，含今天；每日无运行时补零。
- 运行次数、活跃日、星期/小时热力图：所选时段创建的、仍保留的主运行，涵盖重新生成。
- 完成率：已完成 / 已完成、失败、取消之和；进行中不进入分母。无已结束运行时显示空值。
- 主任务 Token：已有运行记录的 `prompt_tokens` / `completion_tokens`，不含子任务；没有提供商回报时不估算。显示回报次数，缺失不同于实际零用量。
- 平均运行用时：已完成运行的 started_at 至 completed_at，包含等待用户、排队或子任务时间；不是纯模型推理耗时。
- 平均会话跨度：所选时段内每个活跃会话的首个运行至最后完成或创建时间，包含空闲时间；不是浏览器前台停留时间，单次未结束运行跨度可为零。
- 模型明细：开启采集后，每次实际 LiteLLM 提供商请求，包括主任务、子任务、上下文压缩、重试及回退，按实际请求模型名分组。成功表示提供商流正常结束，业务运行结果以运行状态为准。
- 工具明细：普通工具执行、子任务工具、运行时编排工具；验证失败与取消计入未完成。审批准备和批准后执行分别记录，后者名称带 `:approval`。

统计是使用分析，不是计费账本。模型调用明细与主任务 Token 的统计来源不同，不能相加。删除会话会级联删除其详细事件并使运行统计同步减少。没有迁移历史对话到事件表。

## 启用

先在 `server/` 执行 `uv run alembic upgrade head`，应用 `0006_usage_events`。默认配置为：

```dotenv
CORNAGENT_TELEMETRY_ENABLED=true
CORNAGENT_TELEMETRY_RETENTION_DAYS=90
```

埋点默认开启，启动前先应用迁移。显式设置 `CORNAGENT_TELEMETRY_ENABLED=false` 可关闭采集，此时不创建采集线程、不写事件；已有运行聚合仍可使用。默认数据库采集器在写入时每小时清理一次超出保留期的事件；无新事件时不触发清理。保留天数范围 1–365。

事件字段是固定白名单：随机事件 ID、服务端身份与会话/运行标识、事件类型、工具或模型名、执行范围、状态、耗时、输入/输出 Token、时间。没有请求正文、提示词、回答、工具参数、文件内容、IP 或邮箱，也不调用第三方分析服务。

## 替换采集器

`server/app/telemetry` 提供 `MetricEvent` 和 `EventSink.write(event)` 协议，通过应用工厂注入：

```python
from app.main import create_app
from app.settings import Settings
from app.telemetry import MetricEvent

class MySink:
    def write(self, event: MetricEvent) -> None:
        # 将白名单指标交给自己的存储或分析服务；外部 IO 必须配置超时。
        ...

app = create_app(Settings(telemetry_enabled=True), telemetry_sink=MySink())
```

采集器在独立消费线程运行；业务协程只向有界队列投递（2048 条），队满即丢弃，采集异常不回传到模型或工具。`app.state.telemetry.dropped/failed` 可供运维读取。关闭时最多等待 2 秒；进程退出可能丢失队列内事件，不重放业务操作。自定义采集器负责自身 IO 超时、保留期限、删除策略和存储安全。使用外部采集器时，页面明确标注明细已交由自定义采集器处理；不会声称能从外部服务读取数据。

自定义模型适配器可通过同一 `bind` 上下文及 `completion` 包装其提供商调用；内置 LiteLLM 已接入。不包装模型文本，不修改运行或 SSE 协议。

## 前端来源与动效

Bklit 官方注册表源码位于 `frontend/src/vendor/bklit`，保留 MIT 许可、来源与下载日期；仅编译所需图表及其依赖。Tailwind 不引入 preflight，页面样式使用 `usage-` 前缀。应用 ESLint 排除第三方源码，TypeScript 与构建仍检查它。

页面入场采用 transitions-polish 的 250ms / 8px / 3px / smooth-out，图表内容揭示 400ms；系统减少动态效果时关闭页面及图表入场。第三方图表算法动画按其语义保留，通过公开参数控制新页面，不批量改动已有聊天动效。

验证覆盖时间范围、补零、无用量、当前身份隔离、删除联动、可选采集器、队列拥塞、采集异常、真实运行模型/工具接入。统计页面与本地预览均连接项目真实服务；无数据时显示空态，不填充示例数据。自动化测试中的合成数据只用于验证。
