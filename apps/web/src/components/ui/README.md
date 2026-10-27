# 共用视觉组件

Button/Popover 沿用公开 shadcn/ui 组合模式与 MIT 许可，样式按 design/07 精简。
业务组件继续负责状态、禁用条件与事件；这里不获取数据、不重算价格、不保存条件。
Radix 负责弹层焦点与关闭行为。只增加实际使用的组件，不引入整套页面或业务抽象。
颜色来自 src/app/tokens.css；方案与依赖见 docs/adr/018-frontend-tailwind-shadcn.md。
