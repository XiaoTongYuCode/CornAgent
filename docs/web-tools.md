# 网络搜索与网页读取

状态：active

主 Agent 与只读子 Agent 共用两个网络工具，接入点为 `server/app/agent/tools/web.py`，由 `create_app` 注册。

- `web_search(query, max_results=5)`：调用 Tavily Search，固定使用 basic、关闭自动参数与生成答案，最多返回 10 个来源。每个来源保留标题、URL 与最多 4000 字符摘要。根目录 `.env` 或服务器环境变量设置 `tavily_api_key`；未配置时返回明确工具错误，不返回模拟结果。
- `read_url(url)`：通过 Tavily Extract 获取公开 HTTP(S) 网页正文，与搜索共用 `tavily_api_key`。固定使用 `basic` 深度、Markdown 格式和 30 秒提取超时，不传 query 以避免将正文缩减为相关片段。返回标题（上游未提供时为空）、请求的来源 URL、最多 24000 字符正文及 `truncated` 标志。不支持登录凭据或私网 URL。实际网络连接只发往固定 Tavily 地址，不由应用直接请求目标站点。

两者使用现有异步 HTTP 客户端，每次调用最长 45 秒，响应体上限 2 MiB。上游限流、网络故障和无效响应均返回工具错误，不回传上游错误正文或密钥；取消会终止异步请求。网页和搜索结果都是不可信资料，模型只提取事实并引用来源，不遵循其中指令。结果沿用现有工具事件、checkpoint 和历史恢复路径。

搜索与提取均使用 Tavily 账户积分。未配置密钥时，读取返回 `WebReaderNotConfigured`；HTTP 200 中的 `failed_results`、无结果或空正文返回工具失败，不当作成功读取。无自动付费升级或跨供应商回退。`mock_web_search` 仅在显式启用 `CORNAGENT_AGENT_MOCK_TOOLS_ENABLED=true` 时供模拟演示使用，默认关闭。

参考：[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)。
