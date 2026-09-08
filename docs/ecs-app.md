# ECS 整站部署

状态：active

React 静态构建与 FastAPI / Agent 运行器在同一台 ECS 上运行，使用本机 PostgreSQL 和 Redis。Caddy 接收公网 HTTPS 请求并自动签发、续签证书，反向代理至仅监听 `127.0.0.1:8000` 的应用；SSE 不缓冲。

## 文件与服务

- 发布目录：`/opt/cornagent/releases/<commit>`；`/opt/cornagent/current` 指向当前版本。
- Python 3.12：`/opt/cornagent/python`；每个版本的 `server/.venv` 使用锁文件安装生产依赖。
- 私有配置：`/etc/cornagent-app/app.env`，权限 `root:cornagent 640`；发布目录 `.env` 链接到该文件，供 Settings 读取。不要把密钥写进 systemd unit 或仓库。
- 持久文件：`/var/lib/cornagent/files`，由 `cornagent` 用户持有。附件开关沿用迁移前设置，不因部署方式变更而自动开启。
- 服务模板：[cornagent.service](../deploy/ecs/cornagent.service)、[Caddyfile](../deploy/ecs/Caddyfile)。数据库备份与证书维护见 [数据库部署](ecs-databases.md)。

数据库连接地址使用 `127.0.0.1`，端口仍为 `55432` / `6380`，保留 TLS、独立密码和 CA 校验。整站切换后数据库只监听本机，同时撤销为 Vercel 新增的公网安全组与防火墙端口。原有 `Petspace` 等独立服务不在本次迁移范围内。

## 发布

1. 在构建机运行 `make build`；将版本化源码及 `frontend/dist` 打包，不包含 `.env`、本机虚拟环境或运行数据。
2. 解压到新发布目录，运行 `uv sync --locked --no-dev --python /opt/cornagent/python/bin/python3.12`。
3. 链接私有 `.env`，停止旧应用后执行 `server/.venv/bin/python -m alembic upgrade head`。升级数据库前运行备份服务。
4. 更新 `current` 链接并重启 `cornagent`；先检查本机 `/readyz`、静态页面和真实 Run。
5. 首次迁移时，把 Cloudflare 中 `cornagent` 的记录改为 ECS 公网 IPv4，保持仅 DNS。加载 Caddy 配置，验证公开 HTTPS 证书、实际回复、SSE、历史恢复及删除。
6. 确认新站可用后，将数据库限制为本机访问，使旧 Vercel 部署不能继续执行后台任务。保留 Vercel 项目不代表继续使用它服务该域名。

Uvicorn 仅信任本机 Caddy 的代理头，不使用 Vercel 的 `forwarded-allow-ips '*'` 设置。模型和工具 API 必须从 ECS 实测可达。

默认包源不可达时，可先用 `uv export --locked --no-dev --no-emit-project` 导出 requirements，再用 `uv pip sync --require-hashes --python .venv/bin/python --index-url <镜像地址> <requirements文件>` 安装；版本与文件哈希仍由锁文件约束。远程执行器超时后应先检查并停止本次残留安装进程，避免重复安装等待同一依赖锁。

## 运维与回退

使用 `systemctl status cornagent caddy`、`journalctl -u cornagent` 和 `journalctl -u caddy` 查看状态。应用崩溃自动重启，Run 恢复依赖数据库检查点和租约；手动重启后应检查历史与运行状态。

代码回退可将 `current` 指向保留版本后重启服务；存在 schema 变更时必须先评估对应数据库恢复，不能仅切代码。回到 Vercel 还需要恢复其数据库网络访问，并恢复原 DNS 记录。不要同时开放多个未经协调的发布入口。
