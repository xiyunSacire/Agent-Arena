"""
HBPU Agent Student Client - 应用程序入口模块

本模块是项目的启动脚本，负责环境初始化、命令行参数解析及客户端引导。
主要职责包括：
.  智能处理 Python 模块搜索路径（sys.path），确保项目根目录被正确索引。
.  兼容多种项目结构（直接运行脚本 vs 包内导入）的导入逻辑。
.  解析命令行参数（如 student_id），提供灵活的运行时配置。
.  作为程序入口点，实例化并启动 ArenaClient 运行循环。

关键流程说明：
.  【环境初始化流程】
.  脚本启动 ──→ 获取当前文件路径
.          │
.          ├──→ 1. 计算项目根目录 (Parent Directory)
.          │       └──→ 检查并注入 sys.path，确保可导入 HBPU_Student_Client 包
.          │
.          └──→ 2. 导入业务逻辑
.                  ├──→ 尝试从包路径导入: from HBPU_Student_Client.example import run_test_client
.                  └──→ (回退) 尝试从本地路径导入: from example import run_test_client
.
.  【参数解析流程】
.  执行 main() ──→ 初始化 ArgumentParser
.          │
.          ├──→ 定义参数: --student-id (默认值: 202340407428)
.          │
.          └──→ 解析参数 ──→ 获取 Namespace 对象
.
.  【启动执行流程】
.  获取 student_id ──→ 调用 run_test_client(student_id)
.          │
.          └──→ 移交控制权给 example.py 中的客户端实例

架构设计说明：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                          main.py (入口层)                           │
.  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │
.  │  │ 路径配置器      │  │ 参数解析器      │  │ 引导器          │      │
.  │  │ (Path Setup)    │  │ (ArgParse)      │  │ (Launcher)      │      │
.  │  └─────────────────┘  └─────────────────┘  └─────────────────┘      │
.  └──────────────────────────────────┬──────────────────────────────────┘
.                                     │ 调用
.                                     ▼
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                     example.py (业务逻辑层)                         │
.  │  ┌───────────────────────────────────────────────────────────────┐  │
.  │  │                   run_test_client (启动函数)                  │  │
.  │  └───────────────────────────────────────────────────────────────┘  │
.  └─────────────────────────────────────────────────────────────────────┘

组件生命周期：
.  [启动期] ──→ 修正 sys.path 环境变量
.  [解析期] ──→ 读取命令行参数 (student_id)
.  [运行期] ──→ 调用 run_test_client 启动 WebSocket 客户端
.  [结束期] ──→ 等待客户端内部循环结束

参数配置说明：
.  ┌──────────────────────┬───────────────────────────────────────────────┐
.  │       参数           │                   说明                        │
.  ├──────────────────────┼───────────────────────────────────────────────┤
.  │ --student-id         │ 指定连接服务器时使用的学生学号                │
.  │                      │ 默认值: 202340407428                          │
.  └──────────────────────┴───────────────────────────────────────────────┘

作者: Sacire
版本: 1.4.0
"""
import argparse
import sys
from pathlib import Path

# 确保直接执行脚本时父级项目目录在模块搜索路径中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from HBPU_Student_Client.example import run_test_client
except ModuleNotFoundError:
    # 直接从包目录运行时，尝试使用本地模块导入
    package_dir = Path(__file__).resolve().parent
    if str(package_dir) not in sys.path:
        sys.path.insert(0, str(package_dir))
    from example import run_test_client


def main() -> None:
    """
    应用程序主入口函数

    该函数负责解析命令行参数并启动客户端测试流程。
    它充当了脚本执行环境与业务逻辑（run_test_client）之间的桥梁。

    执行流程：
    1. 初始化参数解析器：设置脚本描述信息。
    2. 定义启动参数：
       - "--student-id": 接收用户指定的学号，用于连接服务器时的身份标识。
         (默认值: "default001")
    3. 解析参数：从命令行读取输入，若未提供则使用默认值。
    4. 启动客户端：调用 example 模块中的 run_test_client 函数，
       并将解析到的 student_id 传递给它，正式开启 WebSocket 连接循环。

    Args:
        无 (参数通过命令行解析获取)

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description="Run the HBPU Student Client example.")
    parser.add_argument(
        "--student-id",
        default="default001",
        help="Student ID to use when connecting to the server.",
    )
    args = parser.parse_args()

    run_test_client(student_id=args.student_id)


if __name__ == "__main__":
    main()
