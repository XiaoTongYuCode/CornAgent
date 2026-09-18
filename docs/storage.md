# 文件存储设计

状态：active

## 并发与等待边界

接收上传请求体与写入存储使用独立的实例级并发名额，默认各 2 个；请求体缓冲名额保留至写入完成，
因此内存中的文件缓冲数量始终有界。读取请求体时不占用数据库连接或写入名额。
请求体默认 60 秒超时，返回 `file_upload_timeout`（408）；并发名额默认等待 5 秒，
超时返回 `file_operations_busy`（503）。错误或客户端取消都会释放名额。

PDF 提取默认每实例 1 个并发，取得名额后才访问数据库；读取文件与解析期间不保留数据库连接和行锁。
解析完成后重新加锁校验文件状态及摘要，已删除文件不会被恢复，其他实例已完成的提取结果直接复用。
解析失败状态仍持久化，可重试；未完成的进程内解析在服务重启后可重新发起。

配置项见 `.env.example`：`CORNAGENT_FILE_BODY_MAX_CONCURRENCY`、`CORNAGENT_FILE_UPLOAD_MAX_CONCURRENCY`、
`CORNAGENT_FILE_EXTRACTION_MAX_CONCURRENCY`、`CORNAGENT_FILE_UPLOAD_BODY_TIMEOUT_SECONDS` 和
`CORNAGENT_FILE_ADMISSION_TIMEOUT_SECONDS`。并发上限按进程生效；数据库行锁和文件完整性检查保护跨实例提交。

## 选择

PostgreSQL 管理文件元数据与生命周期，私有对象存储保存原文件。默认使用本地文件系统，也可配置 S3 兼容桶。
小型本地项目不额外要求对象存储服务；多进程或多实例部署使用共享持久卷或 S3，所有实例必须看到同一份字节。

| 内容 | 所在位置 |
| --- | --- |
| 文件名、实际 MIME、大小、SHA-256、会话归属、处理与删除状态 | PostgreSQL `cornagent_files` |
| 原始图片、PDF | 私有本地目录或私有 S3 桶 |
| 有界 PDF 提取文本、parser 版本、截断标记 | PostgreSQL，正文存入 `extracted_markdown` |
| 消息对文件的有序引用 | PostgreSQL `cornagent_agent_message_files` |
| SSE、Message、Run checkpoint | 文件 ID、状态和脱敏投影 |
| 模型正在读取的图片或 PDF 页段 | 当前 provider 请求内存 |

没有 base64 入库，没有对象 URL/存储路径进入模型或 SSE，没有 `read_file` 原文或派生图片进入 checkpoint。
不引入附件语义的第二套数据库，不为当前有界附件额外增加向量数据库或搜索服务。

## 读写路径

1. `POST /files` 通过 Idempotency-Key 创建待上传 metadata，服务端生成 UUID 对象键，不使用用户文件名作为路径。
2. `PUT /files/:id/content` 有界读取，检查声明大小、实际格式、图片解码/动画/像素限制，计算 SHA-256。
3. 对象写入成功后标记 `stored`；同键重试仅接受相同字节，已认领文件不可覆盖。
4. PDF 在隔离子进程中使用 `markitdown` 提取，限制页数、字符数和处理时长。
5. 创建 Run 时在数据库事务内锁定并认领附件，变为 `ready`，绑定 Session 和 Message。
6. 内容读取通过同源 API；模型图片请求重新检查归属、大小与 SHA-256，再临时生成 image_url。
7. `read_file` 每次重新验证当前 Session，按 cursor 最多返回 20,000 字符；只保存脱敏工具结果与引用，后续轮次重新物化正文。

当前附件上限较小，上传经过 FastAPI 即可统一执行格式检查；不为此引入浏览器直传及异步确认协议。
存储在 Web 根目录外、由服务控制读取，遵循 [OWASP 文件上传建议](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)。

## 一致性与回收

本地写入先写临时文件并 fsync，再用原子 hard link 发布到唯一对象键；同名不同内容拒绝。
S3 用 `If-None-Match: *` 和 SHA-256 checksum，避免覆盖。可在根目录 `.env` 设置 `CORNAGENT_S3_ACCESS_KEY_ID` / `CORNAGENT_S3_SECRET_ACCESS_KEY`，临时凭据另设 `CORNAGENT_S3_SESSION_TOKEN`；留空时使用 AWS SDK 标准凭据链，支持系统环境变量和部署时的工作负载角色。
目标 S3 兼容服务需支持条件写入与 checksum；不支持时显式失败，不自动降级为覆盖写。
参见 [S3 条件写入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) 与 [对象完整性](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html)。

数据库与对象存储没有分布式事务：对象写入失败不产生可用文件；数据库提交失败留下可被相同内容重试认领的对象。
待上传记录先于对象创建，因此每个正式对象都有数据库记录可追踪。未认领的 `pending/stored` 超过 24 小时自动回收。

删除会话先在同一数据库事务把关联文件标记 `delete_pending` 并解除会话引用，再删除消息树。
后台 collector 每 60 秒处理 tombstone，删除对象后标记 `deleted` 并清除派生正文；失败保留状态重试。
收到删除请求后，内容 API 和工具立即不可读，不等待物理清理。

备份必须同时覆盖 PostgreSQL 与对象存储。使用 S3 版本化桶时，对象删除可能只创建删除标记；历史版本的保留期需由桶生命周期策略管理。
本地存储目录使用私有权限并且被 Git 忽略；部署时不能依赖容器临时文件系统。

## 边界

关闭用户系统时，所有浏览器共享固定 scope；开启后，文件 API 按服务端解析的用户身份校验所有权。两种模式下文件工具均只能读取当前 Session 的附件，不能跨 Session 读取。
身份来源和模式切换规则见[用户系统](authentication.md)。更换浏览器或 IP 导致无感身份变化时，旧附件不会自动转移给新身份。

## PDF 指定页图文读取

`read_file(file_id, page_numbers=[1, 2])` 返回所选页的 Markdown 与内嵌图片；页码从 1 开始，
不可重复或越界。未指定页码时继续使用 `cursor/max_chars` 读取提取文本，两种定位方式不可混用。
扫描版或空白 PDF 的空文本提取可正常完成；图片读取不依赖提取文本非空。

实现使用已锁定的公开 `pypdfium2` 与 MarkItDown，在隔离子进程中读取 PDF 对象里的图片并转成 JPG，
不渲染完整页面。单次最多 16 张图、总 base64 长度 16 MiB，原始图像最多 2500 万像素，输出最长边 2048；
同时受 PDF 页数、文字长度与解析超时限制。按需读取和上传提取共享实例解析名额，获取名额后才读取对象字节。

每次读取重新校验当前 Session、文件生命周期、字节数和 SHA-256，IO 后再次检查归属与状态。
模型请求先保持完整的 tool 响应批次，再追加图像输入；PDF 派生图与直接上传图片合计计入请求图片预算。
checkpoint、公共消息、SSE 仅包含引用、页号和数量，重启/恢复后重新鉴权并读取原文件。

## 文本和 DOCX 附件

支持 TXT、Markdown、CSV、TSV、DOCX；与 PDF 共用配置中的单文档大小限制和总附件字节/数量限制。
`/agent/status` 返回统一白名单。前端按后缀修正 OS 的空 MIME 或 CSV 被标为 Excel 的声明；
服务端仍检验实际字节。文本接受 UTF-8（可带 BOM）及带 BOM 的 UTF-16，拒绝二进制控制字符；
CSV/TSV 保留原始分隔符。DOCX 校验 ZIP 条目数、展开字节上限、加密标记与 Word XML，拒绝 DTD/实体。
提取在有时间和资源限制的子进程内进行，输出段落与表格单元格文本，不执行宏、不请求外链。
不支持旧式 DOC、XLS/XLSX、PPT/PPTX、音视频或压缩包。

文档提取结果继续保存到 FileResource 的既有提取字段，并由 `read_file` 使用 cursor/max_chars 分页。
页码与内嵌图片读取仅支持 PDF。原附件、提取正文、消息引用、归属隔离和删除路径与 PDF 一致。
`GET /files/:id/content?download=true` 返回 attachment disposition；默认 inline。
消息附件显示格式图标、文件名、类型/大小，提供打开/下载操作及图片预览。

## 持久资料与完整工具回执

`cornagent_agent_tool_receipts` 保存不可变的工具结果，独立于有容量限制的模型 checkpoint。
每个回执使用 Run 与工具调用 ID 的稳定组合；同一调用编号再次提交相同参数时复用已保存结果，
公开回执在再次执行 handler 前直接回放，参数变化则拒绝；私有只读来源仍重新鉴权读取。
完整 JSON、SHA-256、大小、来源完整性与只读/失败标记一并入库。
单条结果最多 4 MiB、每个 Run 合计最多 64 MiB；超限明确失败，不把截断结果冒充完整回执。

普通工具回执与批次完成标记、安全 checkpoint 在同一个带租约校验的数据库事务中提交。
大于 8 KiB 的模型上下文结果改为回执引用与预览，完整内容仍可分页回读。
普通工具执行中崩溃仍遵循既有失败边界；数据库回执不提供外部系统的跨事务恰好一次执行保证。

`list_materials`、`search_materials` 提供有界列表与字面量搜索；`read_material` 与
`read_tool_result` 每次最多读取 20,000 字符，沿 `next_cursor` 读至为空可以重建完整 JSON。
完整回执表示完整保存了工具返回值；搜索摘要、上游截断和分页来源仍保留 `source_truncated`
标记，不能把保存成功理解为已经获取外部来源全文，也不能由历史回执推断外部对象当前未变化。

每次读取均校验 tenant、会话所有者与消息分支，只允许当前 Run 和其用户消息祖先对应的 Run；
重新生成的兄弟分支、其他会话和其他身份不可读取。`call_id` 仅定位当前 Run，跨轮使用稳定
`receipt_id` / `material_id`，避免不同轮次的同名调用混淆。会话或 Run 删除时回执由外键级联删除。
资料读取引用绑定原始 Run；续轮物化前重新确认原始 Run 仍属于当前分支，不把旧目录改为新 Run
的目录。成功的 `call_id` 回读规范化为稳定 `receipt_id`。目录每次读取重新鉴权，原始 Run 内
后来新增的资料仍可出现，因此目录不是按时间冻结的外部事实快照。

私有文件派生正文与图片不复制到资料库，只保存脱敏投影和原始读取参数；模型必须通过来源工具
重新鉴权、物化内容。资料读取本身也使用私有结果协议，公共消息、SSE 和 checkpoint 保存读取
引用与页码计数，正文只存在于当前模型请求；资料读取工具不会再生成递归的资料副本。
列表查询只取有界预览，私有正文不参与资料库搜索，无需另建向量数据库。

升级前停止服务，在 `server` 执行 `uv run alembic upgrade head`，应用 `0008_agent_materials`。
