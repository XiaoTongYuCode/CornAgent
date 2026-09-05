# CornAgent 标志

状态：active

用户选定三片构形：三颗饱满的抽象籽粒围合出向右展开的负空间。以单色轮廓作为主要识别元素。

| 文件 | 用途 |
| --- | --- |
| [cornagent.svg](cornagent.svg) | 黑色独立图标，256 × 256 |
| [cornagent-lockup.svg](cornagent-lockup.svg) | 黑色图标与字标，638 × 160 |
| [cornagent-inverse.svg](cornagent-inverse.svg) | 深色背景上的反白图标 |
| [cornagent-lockup-dark.svg](cornagent-lockup-dark.svg) | 深色背景上的反白横版 |
| [cornagent-accent.svg](cornagent-accent.svg) | 玉米黄图标 |
| [preview.png](preview.png) | 横版、反白、辅助色与小尺寸预览 |

所有标志 SVG 都是透明底的填充路径，没有嵌入位图、外部资源、脚本或字体依赖。独立图标只有三个路径。字标使用项目已有的 Inter 600，字距经调整后转为轮廓；Inter 原字体采用 SIL Open Font License 1.1。

横版对齐先以可见轮廓为基准，再按黑色面积重心校正，避免字母 `g` 的下伸部使文字看起来偏高。该校正已包含在 SVG 内，使用方直接等比缩放即可。

主色为 `#171918`，反白为 `#F7F8F5`，辅助色为 `#E8B647`。建议独立图标不小于 24px；保留图形间的负空间，不拉伸、不描边、不加阴影。

概念通过内置 imagegen 探索，按用户选定的左下角方案手工重绘贝塞尔曲线。提示词要点：开源 Agent 产品、三片抽象籽粒、紧凑单色轮廓、清晰负空间、现代无衬线字标。

验证：SVG 结构与资源检查、24/32/64px 栅格化检查、黑白版本一致性、横版光学重心检查。主侧栏直接导入本目录的独立图标，通过 CSS mask 跟随主题；项目 README 使用深浅色横版字标。
