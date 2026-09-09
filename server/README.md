# CornAgent Server

状态：active

基于 FastAPI 的 Agent 服务，使用 PostgreSQL 持久化会话与运行状态，使用 Redis Stream 推送实时事件。提供 checkpoint、暂停恢复、消息版本管理，以及 `ask_user`、`read_file`、Tavily 网络搜索、Jina 网页读取和五个持久化子任务编排工具。子任务支持独立模型上下文、只读工具、取消和租约恢复；协议与扩展入口见 [子任务说明](../docs/subagents.md)。

```sh
uv sync --group dev --locked
createdb cornagent
uv run alembic upgrade head
make dev
```

全部配置见项目根目录 [.env.example](../.env.example)，实际读取根目录 `.env`；系统环境变量可以覆盖文件值。`make dev` 使用配置中的监听地址、端口、日志级别和 reload 开关。项目入口与使用说明见 [根 README](../README.md)，存储设计见 [storage.md](../docs/storage.md)。

用户系统默认关闭；启用方式、SMTP、Passkey 和 `create_app` 的身份／邮件适配接口见[用户系统](../docs/authentication.md)。
PostgreSQL / Redis 的 TLS 配置与维护见 [ECS 数据库部署](../docs/ecs-databases.md)。
前后端与数据库全部运行在 ECS 的步骤见 [ECS 整站部署](../docs/ecs-app.md)。

```sh
make lint
make test
```
