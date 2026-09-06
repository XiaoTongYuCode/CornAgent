# Vercel 部署

状态：active

线上地址：[cornagent.xiaotongyu.com](https://cornagent.xiaotongyu.com)。

根目录 `Dockerfile.vercel` 使用 Vercel Container Images 构建整个应用：先构建 React 前端，再由现有 FastAPI 应用同时提供页面、API 和 SSE。无需修改业务代码。

## 外部服务与配置

在 Vercel 项目环境变量中设置以下配置；密钥和连接串不要写入版本化文件。

| 环境变量 | 配置 |
| --- | --- |
| `CORNAGENT_DATABASE_URL` | 云端 PostgreSQL 的 `postgresql+psycopg://` 连接串，启用 TLS |
| `CORNAGENT_REDIS_URL` | 云端 Redis 的 `rediss://` TCP 连接串，不使用 REST URL |
| `CORNAGENT_AGENT_API_KEY` | 本地 `.env` 中的 OpenRouter 密钥 |
| `CORNAGENT_AGENT_API_BASE` | `https://openrouter.ai/api/v1` |
| `CORNAGENT_AGENT_MODEL` | `openrouter/` 加 OpenRouter 模型 ID |
| `CORNAGENT_ALLOWED_HOSTS` | JSON 数组，包含自定义域名和项目部署域名 |

容器默认关闭附件上传，本地文件路径使用 `/tmp/cornagent/files`。数据库和 Redis 存放持久状态；不要上传本地 `.env`、对话或运行时数据。`.dockerignore` 和 `.vercelignore` 排除这些内容。

镜像构建时预编译 Python 字节码，并设置 `LITELLM_LOCAL_MODEL_COST_MAP=true` 使用安装包内的模型价格表，避免冷启动时额外访问 GitHub。模型调用仍使用配置的 OpenRouter 接口。

`server/vercel_entrypoint.py` 先监听 HTTP，再在首个请求中加载现有应用，避免模型 SDK 导入超过容器监听端口的启动时限。并发首请求共用一次初始化；请求会等待 PostgreSQL、Redis 和应用生命周期启动完成，关闭时执行原有清理流程。首次访问可能稍慢，`/readyz` 仍执行真实依赖检查。

## 发布

1. 在仓库根目录执行 `vercel link`，连接正确的团队和项目。
2. 配置云端 PostgreSQL、Redis 与上述环境变量。
3. 使用云端数据库环境变量，在 `server/` 执行 `uv run alembic upgrade head`；不要使用会尝试创建数据库的本地 `app.setup` 入口。
4. 执行 `vercel deploy --target=preview`，通过 `vercel curl --deployment <预览地址>` 验证 `/readyz`、聊天流和会话恢复，再执行 `vercel promote <预览地址> --yes`，使用同一份源码和生产环境变量发布。
5. 将 `cornagent.xiaotongyu.com` 绑定到项目，按 Vercel 给出的记录配置 DNS。

迁移作为发布步骤执行，不在每个容器启动时运行。

若预览环境开启 Vercel 登录保护，使用 `vercel curl` 验证 API。现有浏览器请求采用 `credentials: 'omit'`，不会携带 Vercel 登录 Cookie，因此真实浏览器聊天在公开的自定义域名上验证；无需为部署修改应用认证行为。

当前项目为 `greenhornxty-3075s-projects/cornagent`，使用 CLI 手动发布，Git 自动部署尚未连接。PostgreSQL 和 Redis 分别使用 Neon 与 Upstash 的免费套餐。

## 运行边界

当前部署使用现有的单一共享作用域，未增加账户系统或工作区隔离。Vercel 会回收空闲实例并限制请求时长，因此长任务和断线后的后台任务不能保证持续执行或立即恢复；数据库中的历史记录仍可在后续请求中读取。

新 Run 按客户端 IP 限流，默认每 IP 6 次/60 秒，使用共享 Redis 在各实例间计数，详见[运行时限流](runtime.md#新-run-的-ip-限流)。
Vercel 容器入口的 Uvicorn 已启用 `--proxy-headers --forwarded-allow-ips '*'`，将平台覆盖写入的 `X-Forwarded-For` 转为 ASGI 客户端地址；应用据此生成限流身份。
该入口只应由 Vercel 网关访问；自托管时必须将可信代理限制为实际代理 IP，不可向公网直连入口照搬通配信任。
Vercel 的请求头覆盖规则见[官方请求头说明](https://vercel.com/docs/headers/request-headers#x-forwarded-for)。

参考：[Vercel Container Images](https://vercel.com/docs/functions/container-images)、[LiteLLM OpenRouter](https://docs.litellm.ai/docs/providers/openrouter)。
