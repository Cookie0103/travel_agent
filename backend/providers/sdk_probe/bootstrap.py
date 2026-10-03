"""等待父进程完成 Job/进程组设置，再启动实际工作程序。"""

import os
import subprocess
import sys


def main() -> int:
    # 不变量：按字节读握手，不能预读留给实际工作程序的请求正文。
    ready = bytearray()
    while len(ready) < 7:
        part = os.read(0, 1)
        if not part:
            return 2
        ready.extend(part)
        if part == b"\n":
            break
    if bytes(ready) not in {b"start\n", b"start\r\n"} or len(sys.argv) < 2:
        return 2
    return subprocess.call(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
