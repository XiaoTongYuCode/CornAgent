# CornAgent

- 默认使用简体中文。
- 首读 README.md、docs/architecture.md、docs/runtime.md、docs/storage.md。
- 项目应能独立安装与运行，依赖使用公开包并提交锁文件。
- 状态机、SSE、消息树与渲染的变更需验证持久化、恢复及前后端一致性。
- 前端首读 frontend/README.md；新增界面文案使用有类型检查的 i18n 字典，不翻译用户或模型内容。
- 语言与主题切换只影响展示，保留会话、SSE 订阅和输入草稿；导航、面板与聊天页复用同一工作区。
- 页面接入通过 frontend/src/agent/index.ts 的公共入口；共用 Provider、工作区、消息操作与渲染组件。
- schema 变更通过 Alembic；Python 用 uv 和 Python 3.12。
- 验证：make check；前端变更另跑 make build。
- 不提交 .env、密钥、用户对话、上传文件或运行时数据。
