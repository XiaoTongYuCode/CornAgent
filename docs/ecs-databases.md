# ECS 数据库部署

状态：active

当前演示站已[整站迁至 ECS](ecs-app.md)，PostgreSQL 和 Redis 仅监听本机。本文记录数据库服务与维护方式，下方 Vercel 连接配置和切换步骤保留为历史方案，当前不开放数据库公网端口。

## 独立服务

- PostgreSQL 17：`postgresql-17.service`，端口 `55432`，数据目录 `/var/lib/pgsql/17/data`。仅 `cornagent` 账号可通过 TLS 和 SCRAM 访问 `cornagent` 数据库；不授予超级用户权限。
- Redis：`cornagent-redis.service`，TLS 端口 `6380`，数据目录 `/var/lib/cornagent-redis`。禁用默认用户，专用 ACL 账号限定 `cornagent:*` 键；启用 AOF，内存上限 128 MiB，使用 `noeviction`。
- 两个服务按用户要求关闭开机启动，当前继续运行。原有数据库及其他服务独立保留，不复用或清空其数据目录。

当前服务通过 `127.0.0.1` 和 TLS 连接数据库，原先供 Vercel 使用的公网安全组及防火墙入口已撤销。历史跨主机方案需要单独评估网络访问范围，不能直接照搬到当前部署。

## 历史跨主机连接配置

在部署环境的 Secret 中配置：

- `CORNAGENT_DATABASE_URL`：`postgresql+psycopg://cornagent:<password>@<ecs-ip>:55432/cornagent`。
- `CORNAGENT_DATABASE_SSL_CA_PEM`：完整 CA PEM。运行时为 libpq 创建私有临时证书文件，并强制 `verify-full`，关闭连接池后删除文件。
- `CORNAGENT_REDIS_URL`：`rediss://cornagent:<password>@<ecs-ip>:6380/0`，查询参数包含 URL 编码的 `ssl_ca_data`（完整 CA PEM）、`ssl_cert_reqs=required` 和 `ssl_check_hostname=true`。

服务器证书的 SAN 必须匹配连接 URL 中的地址。不要使用 `sslmode=disable` 或关闭 Redis 证书校验。密码、CA 私钥和连接配置不进入 Git；服务器私有配置保存在 `/etc/cornagent`，仅 root 可读。CA 公钥可以传给应用，但 CA 私钥不得离开服务器。

## 历史 Vercel 切换步骤

1. 新建独立服务和凭据，验证两端的 TLS、认证和读写；错误 CA、错误密码以及明文连接必须失败。
2. 在 `server` 目录注入以上环境变量，执行 `uv run alembic upgrade head` 初始化新库。
3. 更新 Vercel 生产环境变量，部署 `--prod --skip-domain` 候选版本。旧线上部署在域名切换前继续使用旧配置。
4. 候选版本通过 `/readyz`、真实模型调用、SSE 和历史恢复后，再 promote 切换域名。
5. 切换后重新验证公开域名并删除测试会话。清空迁移仅代表不复制旧聊天数据，不自动删除旧云数据库资源。

## 运维

按用户要求，ECS 上的 `cornagent-databases-maintenance.timer` 已停止并禁用，不再执行每日数据库备份或数据库证书定期维护。保留现有备份与手动维护入口：`systemctl start cornagent-databases-maintenance.service`；脚本见 [维护脚本](../scripts/ecs-databases-maintenance.sh)。手动执行时，证书剩余不足 30 天则使用服务器上的 CA 续签，PostgreSQL reload，Redis restart。PostgreSQL 本地逻辑备份保留 7 天，位于 `/var/backups/cornagent`；这不替代异机备份，主机或磁盘丢失仍需要云备份恢复。

可用 `systemctl status postgresql-17 cornagent-redis cornagent-databases-maintenance.timer` 检查服务，使用 `journalctl -u cornagent-databases-maintenance` 检查备份与续签结果。Redis 的历史事件不是会话事实来源，恢复以 PostgreSQL 快照为准。
