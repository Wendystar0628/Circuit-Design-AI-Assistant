# Circuit Design AI - Program Entry Point
"""
程序入口

职责：
- 仅作为程序的唯一入口点
- 调用 application.bootstrap.run() 启动应用

设计原则：
- 遵循单一职责，不包含任何初始化逻辑
- 所有初始化编排由 application/bootstrap.py 负责
"""

import sys


def main() -> int:
    """
    程序主入口
    
    Returns:
        int: 退出码，0 表示正常退出
    """
    from application.bootstrap import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
