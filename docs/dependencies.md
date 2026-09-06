# 依赖清理与体积分析

状态：active

检查日期：2026-09-06。依据本仓库源码、锁文件、已安装包元数据、`npm explain` 和 Vite / Rollup 构建模块报告；数据对应 `@lobehub/ui` 5.15.7。

## 已清理的直接依赖

前端业务源码、测试和配置均没有引用以下包，已从 `package.json` 和锁文件根节点移除：

- `@dnd-kit/core`
- `@dnd-kit/sortable`
- `@dnd-kit/utilities`
- `emoji-mart`
- `@emoji-mart/data`

这 5 个包由 `@lobehub/ui` 自行声明依赖，仍作为间接依赖安装。前端运行时直接依赖从 15 项降为 10 项；锁文件中的非根包节点仍为 861 项，版本未变化。Rollup 输出中这 5 个包的实际保留代码均为 0 字节。因此本次清理减少维护项，不宣称减少安装量或首屏体积。

## 保留的直接依赖

| 依赖 | 当前用途 |
| --- | --- |
| `react`、`react-dom` | 组件运行时、应用挂载与浮层 Portal |
| `@lobehub/ui` | 流式 Markdown、聊天消息布局、滚动区、加载状态与主题 Provider |
| `antd` | 弹窗、搜索浮层、输入、问题选项、骨架屏与主题 |
| `lucide-react` | 应用通用图标 |
| `motion` | 文字切换、消息过程展开/收起与 Lobe Provider 的动画接口 |
| `canvas-confetti` | 作者署名和回答完成的庆祝动画 |
| `thinking-orbs` | 首页及生成中的动态球体 |
| `@fontsource/inter` | 400、500、600 字重的本地字体 |
| `dayjs` | 中英文切换时同步日期语言，供组件库使用 |

开发依赖用于 TypeScript、Vite、ESLint、Vitest、DOM 模拟、组件测试和类型声明，未发现可直接删除的闲置项。直接导入的包应保留为直接依赖，不能仅因组件库也依赖它就删掉声明。

## 后续可优化的体积

当前入口 JS 为 **3,586,659 字节**，gzip 后 **944,912 字节**。下表的模块数字是 Rollup `renderedLength`，在压缩前统计，不能直接相加当作下载体积。

| 方向 | 本次证据 | 调整前提 |
| --- | --- | --- |
| Markdown 提示块的图标数据 | `@lobehub/ui → rehype-github-alerts → @primer/octicons`；Octicons 在入口保留约 997 KB 模块代码 | 优先检查是否能按需加载提示块，或使用精简图标实现；需保留现有提示块渲染 |
| 代码高亮及图表 | `@shikijs/langs` 保留 260 个非空模块约 8.55 MB，主题 65 个模块约 1.47 MB，Mermaid 自身约 2.73 MB；均位于非入口 chunk | 可评估常用语言/主题白名单、图表按需加载；这些不是首屏一次下载量 |
| 字体资源 | 3 个 Inter 字重输出 42 个资源文件，合计 668,360 字节，包括多语种分片与 WOFF / WOFF2 | 可限定所需分片或格式；其他字符需有合适的系统字体回退，浏览器本来就按需请求分片 |
| 替换 `@lobehub/ui` | 多个正式组件依赖其流式 Markdown、消息布局和 Provider | 属于组件改造，不是无用依赖清理；需重验 Markdown、代码块、公式、图表、流式效果及深浅主题 |

`thinking-orbs` 在入口保留约 14.7 KB、`canvas-confetti` 约 24.9 KB 模块代码，并承担现有交互，不优先替换。`antd`、`motion` 和 `dayjs` 均有实际调用，也不能通过删除直接声明获得体积收益。

后端暂未改动：PostgreSQL 驱动由 SQLAlchemy 根据连接 URL 动态加载，S3、PDF、图片、模型调用及服务热重载都有对应依赖，不能只依据顶层 import 判断无用。`httpx` 虽无业务直接导入，但模型客户端与测试客户端需要它；`python-dotenv` 由设置组件间接使用。简化这些声明也不会直接移除对应安装包。

## 验证

清理后执行 `make check`、`make build`；结果记录在 [测试与验证](verification.md)。锁文件除根直接依赖清单外没有变化，业务代码和公开接口没有改动。
