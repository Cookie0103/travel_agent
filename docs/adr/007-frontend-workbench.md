# ADR-007 旅行工作台依赖与契约

状态：accepted，2026-10-03。落实ADR-000既定Next.js App Router / TypeScript / pnpm，不改业务设计或SDK路线。

- Next.js / React / React DOM提供网页运行；TypeScript及官方类型供静态检查。版本经官方文档/registry核对后由pnpm锁文件保存，不使用canary。
- ESLint与Next官方规则、Prettier做前端lint/格式；没有Tailwind、组件库、状态库或第二套Agent runtime。布局用CSS，交互用React状态和fetch。
- openapi-typescript仅作开发时类型生成，读取本项目FastAPI公开契约；不手写另一份请求/schema，也不访问付费API。展示结果的有界应用事件契约由同一后端类型生成。
- Next rewrite代理本机API路径，复用后端Bearer身份；不把供应商密钥暴露浏览器。默认本机开发，不发布。
- SSE用fetch读取以携带Authorization、序号去重并补读；不为浏览器EventSource无Bearer头的限制新增第三方库。
- 默认离线流程是明确标注的固定演示，调用相同业务工具/DB；不能算模型质量。真实模型仍走既有Claude Agent SDK、费用与授权边界。
- 本轮不引入浏览器自动化运行库；用已安装浏览器工具验证实际页面，后续若需回归框架另写ADR。

参考：[官方安装/Node要求](https://nextjs.org/docs/app/getting-started/installation)、[官方rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites)。本机Node24.12.0满足官方最低20.9，具体兼容由构建/页面验证。

实施验证：pnpm11使用pnpm-workspace.yaml的storeDir/allowBuilds；旧.npmrc不再生效。ESLint10/TS7与官方插件peer冲突，固定ESLint9.39.5/TS5.9.3（9版本已被上游标为不再维护，升级需等待插件兼容并另验）；peer检查通过。不执行unrs-resolver安装脚本，使用随包发布的原生依赖，lint/build已验证。前端测试用Node24原生TypeScript/test，不新增测试框架依赖。
