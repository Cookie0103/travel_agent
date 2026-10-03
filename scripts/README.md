# 开发辅助命令

这里给开发者使用，不是旅行 Agent 的业务执行代码。实际测试代码单独放 tests/。

- dev.py / main：根据命令安装环境、检查代码、启动测试或启动本地数据库。
- fetch_upstream.py / main：下载指定版本的参考代码到 vendor/，已有目录不随意覆盖。

例如运行 dev.py test，只是启动 pytest；pytest 再读取 tests/ 中的测试。
Agent 的模型调用与工具循环以后放 backend/agent，不放在这里。
环境阻塞记录统一写入 docs/blocked/environment.md。

不变量：前一步失败就返回失败，不能让后一步的成功掩盖它；默认测试不调用真实模型。
