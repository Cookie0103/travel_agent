# ADR-018：前端 Tailwind CSS 与 shadcn/ui 渐进迁移

日期：2026-10-09。范围：T7.1–T7.5；实时任务状态只在批次计划 §4。

## 背景

用户要求按 design/07 重构已有前端，减少重复样式及过时 CSS，保持业务行为。
旧 globals.css 为 1091 行，颜色/字号与已确认规范不同；layout 还依赖外部字体下载。
既有按钮、表单、弹层和双栏可以继续复用，不新增后端字段、接口或运行时。

用户本轮明确授权从已推送的 76b33fb 开始 T7，分支为
`batch/2026-10-10-frontend-restyle`；这是开发顺序调整，不代表 R6 已验收或允许生产切换。

## 选择与备选

- 采用 Tailwind CSS 4 与其 PostCSS 集成，统一 token，渐进迁移。
- 采用 shadcn/ui 的 Button、Popover 源码模式，按需引入组件；Radix 处理弹层键盘、焦点和关闭行为。
- 运行依赖仅 `@radix-ui/react-slot`、`@radix-ui/react-popover`、`class-variance-authority`、`clsx`、`tailwind-merge`；构建依赖为 `tailwindcss`、`@tailwindcss/postcss`、`postcss`。已查 registry 并精确锁定：Tailwind/PostCSS插件4.3.3、PostCSS8.5.29、Radix Slot1.4.0/Popover1.2.0、cva0.7.1/clsx2.1.1/tailwind-merge3.7.0；锁文件由 pnpm 生成。
- 不引入整套预制页面、图标包、外部字体、暗色模式、日期计算库或另一个状态管理器。日期输入继续使用现有原生控件，未完成的原生日期验收不冒称完成。
- 继续仅用旧 CSS：依赖最少，但不符合已决定的 Tailwind/shadcn 路线，重复样式与弹层行为仍要手工维护。
- 全量组件库或一次替换全页面：改动面大、默认样式难以收敛，不采用。

## 实施边界

1. 建立 design/07 的颜色、系统字体、四档字号、间距、圆角 token；初期保留旧 CSS 兼容映射。Tailwind reset 与旧全局规则需要显式层次，防止优先级冲突。
2. 行程卡契约 `UiPlanCard.start/end` 均为必填带时区时间（REASONED：域模型与生成契约）。仅按日本时区归类：17:00 前白天，其余晚上；无效历史时间独立显示“时间待定”，不得猜时间。
3. 现有UiPlanCard无运输角色字段（REASONED：生成契约）；不制造到达/出发卡，也不从景点名称或硬条件文本猜航班，保留原项与明确说明。
4. 保留全局卡片索引、校验锚点、报价失效、确认禁用、锁定、差异、数据来源、消息重试与去重逻辑。
5. 窄屏用对话/行程标签切换，宽屏双栏；助手白底不加气泡，用户主色底用深色文字；工具步骤维持折叠。
6. 每块独立测试/构建与 Chrome 验收，最后删除无引用的旧选择器及手写弹层代码。无业务变更、真实模型/旅行 API 调用或 Railway 操作。

## 验证与回退

- `pnpm run typecheck/lint/test/build`，CI 三任务；时间分段新增行为先红测试，既有业务回归不弱化。
- 每次 build 后将 `.next/static` 复制到 `.next/standalone/.next/static`，重新启动受控前端并检查脚本 HTTP 状态，避免 P73 复发。
- Chrome 验收宽窄屏、键盘、弹层、滚动、消息/失败、报价/行程、其他页面；截图必须实际查看，未完成项明确记录。
- 不迁移数据库。每块可用普通 revert 回退；最终回退移除新增构建/依赖和 token，并恢复旧 CSS，不 reset/改写历史。

## 官方依据

- [Tailwind 与 Next.js 集成](https://tailwindcss.com/docs/installation/framework-guides/nextjs)。
- [shadcn/ui Next.js 安装](https://ui.shadcn.com/docs/installation/next)。
- [shadcn/ui 组件源码与许可](https://github.com/shadcn-ui/ui)。仅使用公开上游源码并记录来源，不复制 vendor 内部材料。
