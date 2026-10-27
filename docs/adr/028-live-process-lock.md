# ADR-028：运行互斥随进程退出释放

状态：accepted（2026-10-15，用户要求恢复Railway持续blocked并修复残留锁）。

## 证据与决定

旧版用`active.lock`文件存在性作为整轮互斥，并只在Python finally中删除。线上旧Claude轮次在09:04:13开始，容器09:04:55关停、09:05:06停止；随后多个新请求3–12ms内blocked，未启动模型worker。旧部署已REMOVED，当前配置/数据库健康；线上残留文件因未配置SSH不能直接读取，线上原因仍为强证据推断。本地重现“旧标记存在”和“真实子进程被kill未执行finally”均阻止下一轮。

采用标准库内核文件锁：Linux/macOS使用`fcntl.flock(LOCK_EX|LOCK_NB)`，Windows使用`msvcrt.locking(LK_NBLCK)`锁首字节。句柄关闭或进程退出释放占用；文件保留且不unlink，防止新旧inode分别被锁。旧无主标记不影响获取，活跃新进程仍互斥。首次上线前已核对旧容器停止、当前旧版启动后的失败均未进入worker；旧版和新版不得混用，回退旧版前必须停掉新版并确认无活跃执行。

账本、预占、未结算尝试及对话记录均不删除/清零；取得锁后仍按原费用守卫逐HTTP预占。不依据文件年龄、PID存活或超时盲删。重复请求仍拒绝并发，不自动重放被部署中断的模型请求。

live服务器启动只核对获取并释放锁，打印`live_lock_ready`或`live_lock_unavailable`固定事件，不读取/输出正文或密钥，不触发模型、费用或供应商调用；忙时继续启动服务但实际live请求仍受互斥保护。此检查是锁可用证据，不代表一次完整模型回答成功。

备选：临时注册SSH key后手删旧锁不能解决下次部署；按时间删除可能破坏仍活跃的执行；引入新锁库没有必要。复用原exclusive入口，不增加依赖或第二运行时。

来源：[Python fcntl](https://docs.python.org/3/library/fcntl.html#fcntl.flock)、[Python msvcrt](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)。本机真实进程互斥/kill恢复已验证；Windows执行依赖原生平台，当前仅静态三平台检查，不能声称已实跑Windows。
