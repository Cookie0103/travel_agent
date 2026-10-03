"""模拟供应商本地启动入口；沿用Windows兼容事件循环，无真实预订。"""

import argparse

import uvicorn

from mock_supplier.app import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Travel模拟供应商")
    parser.add_argument("--faults", action="store_true", help="显式启用测试/演示故障")
    arguments = parser.parse_args()
    uvicorn.run(
        create_app(faults_enabled=arguments.faults),
        host="127.0.0.1",
        port=8001,
        loop="backend.server:loop_factory",
    )
