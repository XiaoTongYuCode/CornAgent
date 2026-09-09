# 可选用户系统

状态：active

默认 `CORNAGENT_USERS_ENABLED=false`，所有浏览器继续使用原有共享工作区。设为 `true` 后，
`CORNAGENT_AUTH_MODE` 才生效：默认 `invisible`，也可切换为 `account`。修改配置需重启服务。
两种模式的身份均进入现有 `Identity`，隔离会话、消息、Run、问答、附件、幂等键、SSE 与工具读取；
Agent 核心不依赖登录协议。系统不提供组织、管理员或角色管理。

## 模式选择

| 用户系统 | 鉴权模式 | 浏览器体验 | 数据范围 |
| --- | --- | --- | --- |
| 关闭（默认） | 配置不生效 | 直接进入 | 所有浏览器共享工作区 |
| 开启 | `invisible`（默认） | 自动建立访客 Cookie | IP＋浏览器对应的私有工作区 |
| 开启 | `account` | 邮箱验证码、密码或 Passkey 登录 | 稳定邮箱账号的私有工作区 |

本机完整示例见 [README](../README.zh-CN.md#用户系统)，演示站开启无感登录的部署记录见 [ECS 部署](ecs-app.md#演示站部署记录)。

## 启用

1. 按 [.env.example](../.env.example) 配置。生成至少 32 字符随机 `CORNAGENT_AUTH_SECRET`，存入部署密钥管理器；
   多实例使用同一持久密钥，不在日志、前端或仓库中保存。
2. `CORNAGENT_AUTH_ORIGIN` 设置为浏览器访问的完整来源，例如 `https://agent.example.com`，无末尾 `/`。
   HTTPS 使用默认 `CORNAGENT_AUTH_COOKIE_SECURE=true`；仅本机 HTTP 调试设置为 `false`。
3. 安装锁定依赖并构建前端；已有实例先备份并停止服务，再在 `server/` 执行 `uv run alembic upgrade head`，完成后重启。
   `0005_optional_users` 创建独立鉴权表，迁移不分配或改写已有聊天的所有权。
4. 代理必须只信任实际反向代理来源，由 ASGI 层处理客户端地址。应用不自行信任 `X-Forwarded-For`。
   不要把允许任意客户端伪造来源的代理配置用于无感模式。

关闭用户系统后恢复共享数据视图；启用期间的私有数据仍留在数据库中，不变成公共历史。
切换模式也不会自动合并身份。上线前应明确选择模式，避免用户误以为切换模式会迁移聊天。

## 无感模式

浏览器首先请求 `POST /api/v1/auth/session`，取得一年期、HttpOnly、SameSite=Strict 的随机签名 Cookie。
服务端使用 HMAC 将浏览器凭据与规范化的客户端 IP 合成私有工作区标识；数据库不保存原始 IP。
同一 IP 的不同浏览器不共享历史，伪造用户 ID 或转发请求头不能选择其他用户。

这是一种访客工作区识别方式，不证明人的身份，也不是机器硬件绑定。不采集浏览器指纹或硬件信息。
更换 IP、清除 Cookie、换浏览器或无痕窗口会进入另一份工作区；恢复同一 IP 和 Cookie 可再次访问。
轮换 `CORNAGENT_AUTH_SECRET` 会使原无感凭据失效。需要可靠的跨设备恢复时使用邮箱账号模式。

## 邮箱账号模式

设置 `CORNAGENT_AUTH_MODE=account`，配置 SMTP 主机、发件地址和认证信息。邮件通过标准 SMTP STARTTLS
发送，不绑定云厂商；未提供 SMTP 配置或注入的发送器时启动失败。真实邮件送达需部署者用自己的邮箱验证。

登录页提供邮箱验证码、邮箱加密码、Passkey：

- 首次完成邮箱验证会创建账号；后续验证码直接登录。邮箱大小写统一，邮箱验证码不在 API 响应或日志中返回。
- 验证码有效期 10 分钟，绑定发起验证的浏览器；单次使用，最多尝试 5 次。发送和登录按来源 IP、邮箱
  执行数据库共享限流，错误请求不会透露邮箱是否已注册。此版本固定窗口为 10 分钟，邮件 5 次、登录 20 次。
- 验证邮箱时可显式设置或重置 8–128 字符密码，使用公开 `argon2-cffi` 的 Argon2id；重置撤销该账号所有旧登录会话。
- 本地使用 Passkey 时，浏览器地址与 `CORNAGENT_AUTH_ORIGIN` 均使用 `http://localhost:端口`，不能使用 IP 地址作为 RP ID。内嵌浏览器若不支持系统验证器，请在 Chrome 或 Safari 中打开。
- 最近 10 分钟内完成登录的用户可添加 Passkey（超时需退出后重新登录）；登录支持可发现凭据。使用公开 `webauthn` 与 `@simplewebauthn/browser`，
  校验单次挑战、Origin、RP ID、用户验证标志、签名、用户句柄和签名计数。RP ID 从配置的来源主机推导，
  不接受请求中指定的任意 RP ID。更换域名后需要重新登记 Passkey。邮箱验证码可用于找回登录能力。
- 默认登录有效期 7 天，可用 `CORNAGENT_AUTH_SESSION_SECONDS` 配置。浏览器只持有随机 HttpOnly Cookie，数据库只保存
  token 摘要。退出立即撤销该会话；API 每次鉴权，运行中的 SSE 也重新检查会话失效。
- 写请求要求同源 Origin；非浏览器客户端需发送 `X-CornAgent-Request: 1`。响应禁止缓存；不启用跨域 CORS。
  API 客户端需保留 Cookie。前端 JSON、SSE、附件共用同源凭据，身份切换清理旧工作区。退出成功立即清除私有页面，即使后续状态刷新失败；过期的状态请求不能恢复旧身份。

## 可插拔边界

`create_app(identity_provider=..., email_sender=...)` 接收两个公开 Python Protocol：

- `app.auth.provider.IdentityProvider.authenticate(request) -> Identity`：可替换为宿主系统身份解析。
  返回可信、稳定且满足数据库字段长度的身份；失败抛出 `DomainError`（401/403）。内置适配器提供可选
  `bootstrap(request, response)`，宿主适配器只实现 `authenticate` 也可工作。注入自定义身份适配器时关闭内置账号端点和账号控件，不要求 SMTP 配置。
- `app.auth.email.EmailSender.send_code(recipient, code)`：替换邮件供应商；生产发送器不得记录验证码。

`frontend/src/app/AuthGate.tsx` 是应用层登录入口；共享 `frontend/src/agent` 不包含登录页面。
嵌入方可自建认证 UI，先建立同源登录 Cookie，再向 `CornAgentProvider` 传入稳定的 `principalKey`。
切换用户须同步更新该键。跨域嵌入需要宿主提供自己的认证 transport，此版本内置 Cookie 方案仅支持同源。

实现只参考 Cintel 的身份组合、Auth Center 的登录挑战设计，没有复制 EigenLogic 源码或依赖其服务。
依赖均为公开包，Python 与前端提交锁文件。

## 验证

`make check`、`make build`。`server/tests/test_auth.py` 覆盖关闭模式、无感标识、跨用户会话/附件/SSE、
密码、退出、验证码重放/次数/有效期/浏览器绑定、CSRF，以及真实签名的 WebAuthn 注册与认证。
浏览器验证使用测试邮箱发送器与 Chromium 虚拟认证器，另以真实软件签名验证 WebAuthn；不等同于真实 SMTP 投递或物理 Passkey 设备兼容性验证。

安全设计参考 [OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
和 [py_webauthn 官方文档](https://duo-labs.github.io/py_webauthn/registration.html)。
