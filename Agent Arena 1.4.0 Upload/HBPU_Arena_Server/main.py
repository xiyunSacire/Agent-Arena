"""
HBPU Agent Arena Server - 主程序入口

本模块是整个 FastAPI 应用的启动核心，负责：
.  初始化 FastAPI 应用实例及其生命周期管理。
.  注册全局中间件（如 CORS）。
.  挂载 API 路由。
.  配置并启动 Uvicorn ASGI 服务器。

关键流程说明：
.  【应用启动流程】
.  执行 python main.py ──→ uvicorn.run() 启动服务器
.          │
.          ├──→ 1. 创建全局单例组件
.          │       │
.          │       ├──→ ConnectionManager()  # WebSocket 连接管理器
.          │       └──→ LLMEvaluator()       # LLM 评分器
.          │
.          ├──→ 2. 执行 lifespan 启动阶段
.          │       │
.          │       ├──→ 打印服务启动信息（地址、端口、文档地址等）
.          │       │
.          │       └──→ yield 交出控制权，开始接收请求
.          │
.          ├──→ 3. 创建 FastAPI 应用实例
.          │       │
.          │       ├──→ 绑定 lifespan 生命周期管理器
.          │       │
.          │       └──→ 将单例组件附加到 app.state
.          │               ├──→ app.state.manager = manager
.          │               └──→ app.state.evaluator = evaluator
.          │
.          ├──→ 4. 注册中间件
.          │       │
.          │       └──→ CORS 跨域中间件（允许所有来源访问）
.          │
.          ├──→ 5. 注册路由
.          │       │
.          │       ├──→ websocket.router  # /ws/{student_id}
.          │       └──→ admin.router      # /admin/*
.          │
.          └──→ 6. 开始监听请求
.                  │
.                  ├──→ HTTP 请求 → 对应路由处理
.                  └──→ WebSocket 连接 → websocket_endpoint 处理
.
.  【请求处理流程】
.  客户端请求到达 ──→ FastAPI 路由系统
.          │
.          ├──→ HTTP 请求（如 /admin/publish_task）
.          │       │
.          │       ├──→ 通过 request.app.state 获取共享组件
.          │       │       ├──→ request.app.state.manager
.          │       │       └──→ request.app.state.evaluator
.          │       │
.          │       └──→ 执行对应路由函数，返回 JSON 响应
.          │
.          └──→ WebSocket 请求（/ws/{student_id}）
.                  │
.                  ├──→ 建立长连接
.                  │
.                  ├──→ 通过 websocket.app.state 获取共享组件
.                  │
.                  └──→ 循环接收/发送消息
.
.  【应用关闭流程】
.  收到终止信号（Ctrl+C）──→ 触发 lifespan 关闭阶段
.          │
.          ├──→ 执行 yield 之后的清理代码
.          │
.          └──→ 优雅关闭所有连接，释放资源

架构设计说明：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                          main.py (入口)                               │
.  │  ┌─────────────────────────────────────────────────────────────────┐│
.  │  │                    FastAPI Application                          ││
.  │  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ││
.  │  │  │   app.state     │  │   CORS 中间件    │  │   路由系统      │  ││
.  │  │  │  ┌───────────┐  │  │                 │  │  ┌───────────┐  │  ││
.  │  │  │  │ manager   │  │  │  allow_origins  │  │  │ /admin/*  │  │  ││
.  │  │  │  │ evaluator │  │  │  = ["*"]        │  │  │ /ws/*     │  │  ││
.  │  │  │  └───────────┘  │  │                 │  │  └───────────┘  │  ││
.  │  │  └─────────────────┘  └─────────────────┘  └─────────────────┘  ││
.  │  └─────────────────────────────────────────────────────────────────┘│
.  └─────────────────────────────────────────────────────────────────────┘
.                                    │
.                                    │ 依赖注入
.                                    ▼
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                        核心组件层                                    │
.  │  ┌─────────────────────────┐    ┌─────────────────────────────────┐ │
.  │  │   ConnectionManager     │    │        LLMEvaluator             │ │
.  │  │  - active_connections   │    │  - evaluate()                   │ │
.  │  │  - tasks 缓存           │    │  - 调用 LLM API                 │ │
.  │  │  - broadcast_task()     │    │  - 返回评分结果                 │ │
.  │  └─────────────────────────┘    └─────────────────────────────────┘ │
.  └─────────────────────────────────────────────────────────────────────┘
.                                    │
.                                    │ 数据持久化
.                                    ▼
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                         数据层                                       │
.  │  ┌─────────────────────────┐    ┌─────────────────────────────────┐ │
.  │  │   SQLAlchemy ORM        │    │          SQLite 数据库           │ │
.  │  │  - Student 模型         │    │         arena.db 文件            │ │
.  │  │  - Score 模型           │    │                                 │ │
.  │  └─────────────────────────┘    └─────────────────────────────────┘ │
.  └─────────────────────────────────────────────────────────────────────┘

组件生命周期：
.  ┌──────────────────────────────────────────────────────────────────────┐
.  │                         时间线                                        │
.  ├──────────────────────────────────────────────────────────────────────┤
.  │                                                                      │
.  │  [启动]                                                              │
.  │     │                                                                │
.  │     ├──→ manager = ConnectionManager()    # 单例创建，全局唯一        │
.  │     ├──→ evaluator = LLMEvaluator()       # 单例创建，全局唯一        │
.  │     ├──→ lifespan 启动阶段执行              # 打印启动信息             │
.  │     ├──→ app = FastAPI(...)               # 应用实例化               │
.  │     ├──→ CORS 中间件注册                   # 跨域配置                 │
.  │     ├──→ 路由注册                          # 挂载 API 端点            │
.  │     └──→ 开始监听请求                      # 服务就绪                 │
.  │                                                                      │
.  │  [运行中] ──────────────────────────────────────────────────────────→ │
.  │     │                                                                │
.  │     ├──→ 接收 HTTP 请求 → 路由处理 → 返回响应                         │
.  │     ├──→ 接收 WebSocket 连接 → 长连接管理 → 消息收发                   │
.  │     └──→ 所有组件共享同一个 manager 和 evaluator 实例                 │
.  │                                                                      │
.  │  [关闭]                                                              │
.  │     │                                                                │
.  │     └──→ lifespan 关闭阶段执行 → 资源清理 → 进程退出                   │
.  │                                                                      │
.  └──────────────────────────────────────────────────────────────────────┘

配置参数说明：
.  ┌─────────────────────────┬────────────────────────────────────────────┐
.  │       参数               │                   说明                      │
.  ├─────────────────────────┼────────────────────────────────────────────┤
.  │ host                    │ 服务器监听地址（0.0.0.0 监听所有网卡）        │
.  │ port                    │ 服务器监听端口（默认 8000）                   │
.  │ reload=True             │ 开发模式热重载，代码变更自动重启              │
.  │ log_level="info"        │ 日志级别，输出信息、警告、错误等              │
.  │ ws_max_size=10MB        │ WebSocket 单帧最大消息大小                   │
.  │ timeout_keep_alive=120s │ HTTP Keep-Alive 连接超时时间                 │
.  └─────────────────────────┴────────────────────────────────────────────┘

作者: Sacire
版本: 1.4.0
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from config import settings
from api import admin, websocket
import uvicorn
from core.connection import ConnectionManager
from core.evaluator import LLMEvaluator

# 在全局作用域创建核心组件的单例，确保在整个应用生命周期内共享同一个实例
manager = ConnectionManager()
evaluator = LLMEvaluator()

# --- 应用生命周期管理 Lifespan Manager (解决 on_event 警告) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # === 启动阶段 (Startup) ===
    # 打印服务启动信息到控制台，方便开发和调试
    print("=" * 60)
    print("🚀 HBPU Agent Arena Server 启动成功！")
    print(f"📡 服务地址: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
    print(f"📄 API文档: http://localhost:8000/docs")
    print(f"🗃️ 数据库: {settings.DATABASE_URL}")
    print(f"⚙️  WebSocket最大消息大小: 10MB")
    print(f"⏱️  连接保持超时: 120秒")
    print("=" * 60)
    # yield 关键字将控制权交还给 FastAPI，应用开始处理请求
    yield
    # === 关闭阶段 (Shutdown) ===
    # 在此处可以添加应用关闭时需要执行的清理工作，例如关闭数据库连接池等
    # print("正在关闭服务器...")

# --- FastAPI 应用实例化 ---
app = FastAPI(title="HBPU Agent Arena Server", lifespan=lifespan) # API 标题，会显示在 /docs 页面 lifespan=lifespan绑定生命周期管理函数
# 将全局单例对象附加到 app.state 上，以便在路由中通过 request.app.state 访问
# 这是一种推荐的依赖注入模式，避免了使用全局变量
app.state.manager = manager 
app.state.evaluator = evaluator

# --- 中间件配置 ---
# 配置 CORS 中间件，允许前端跨域访问后端 API
# 在生产环境中，应将 allow_origins 设置为具体的前端域名列表，而不是 ["*"]
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 路由注册 ---
# 将各个功能模块的路由注册到主应用中
app.include_router(websocket.router)
app.include_router(admin.router)

# --- Entry Point ---
if __name__ == "__main__":
    uvicorn.run(
        "main:app",                     # 指定要运行的应用，格式为 "文件名:应用实例名"
        host=settings.SERVER_HOST,      # 从配置中读取服务主机地址
        port=settings.SERVER_PORT,      # 从配置中读取服务端口号
        reload=True,                    # 开发模式下启用热重载，代码修改后自动重启
        log_level="info",               # 设置日志级别为 "info"
        ws_max_size=10 * 1024 * 1024,   # WebSocket 单帧消息最大长度限制（字节）。默认通常为 16MB，此处设为 10MB 以防止超大代码片段或长文本传输导致内存溢出或服务拒绝
        timeout_keep_alive=120          # HTTP Keep-Alive 连接的空闲超时时间（秒）。设为 120 秒以确保在客户端进行长耗时任务（如 LLM 推理）期间，连接不会因静默超时而意外断开
    )