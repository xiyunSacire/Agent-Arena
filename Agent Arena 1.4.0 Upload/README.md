# HBPU Agent Arena 1.4.0

HBPU Agent Arena 是一个轻量级的分布式任务评测系统，包含服务端（Arena Server）和客户端（Student Client）。服务端负责发布任务、收集答案并利用大语言模型（LLM）进行自动评分，客户端则用于连接服务端、接收任务、执行自定义逻辑并提交结果。

## 目录结构说明

*   `HBPU_Arena_Server/`: 服务端代码目录。
    *   `main.py`: FastAPI 应用主入口，负责初始化、路由注册和生命周期管理。
    *   `config.py`: 配置管理模块，管理数据库、服务器和 LLM 相关的配置。
    *   `utils.py`: 工具函数模块。
    *   `api/`: API 路由目录（WebSocket 通信、管理端接口）。
    *   `core/`: 核心业务逻辑（连接管理、LLM 评分器）。
    *   `database/`: 数据库模型和会话管理。
*   `HBPU_Student_Client/`: 客户端代码目录。
    *   `client.py`: WebSocket 客户端核心，处理连接、重连、任务调度和结果回传。
    *   `config.py`: 客户端配置，如服务器地址、重连策略等。
    *   `handlers.py`: 任务处理器的定义位置。
    *   `main.py`: 客户端启动入口。
    *   `models.py`: 客户端数据模型（Task, Answer 等）。
    *   `example.py`: 客户端使用示例。

## 服务端 (HBPU_Arena_Server)

服务端基于 FastAPI 构建，使用 WebSocket 与客户端进行实时通信，并集成 LLM 自动评估学生提交的答案。

### 运行环境配置

1.  **依赖安装:** 确保已安装所需的 Python 包（如 `fastapi`, `uvicorn`, `websockets`, `pydantic-settings`, `sqlalchemy` 等）。可以使用 `pip install -r requirements.txt` (如果提供了该文件) 或手动安装。
2.  **配置修改:** 修改 `HBPU_Arena_Server/config.py` 中的配置项：
    *   `DATABASE_URL`: 数据库连接字符串，默认使用 SQLite。
    *   `SERVER_HOST` / `SERVER_PORT`: 服务端监听的地址和端口，默认 `0.0.0.0:8000`。
    *   `LLM_BASE_URL`: 大语言模型 API 接口地址，默认 `https://api.deepseek.com`。
    *   `LLM_PROVIDER`: 模型提供商。
    *   `LLM_MODEL`: 使用的模型名称。
    *   `LLM_API_KEY`: **请务必替换为您自己的 API Key。**

### 启动服务端

在 `HBPU_Arena_Server` 目录下执行：

```bash
python main.py
```

服务端启动后，默认在 `http://localhost:8000` 监听。您可以访问 `http://localhost:8000/docs` 查看 API 文档（如果是 HTTP 接口）。

## 客户端 (HBPU_Student_Client)

客户端用于连接到 Arena Server，自动接收任务，并调用您编写的处理器（Handler）生成答案并提交。

### 运行环境配置

1.  **依赖安装:** 确保安装了 `websockets` 和 `pydantic` 等依赖。
2.  **配置修改:** 检查并修改 `HBPU_Student_Client/config.py` 中的服务器地址等信息。确保 `SERVER_URL` 指向您运行的服务端地址（如 `ws://localhost:8000`）。

### 编写任务处理器

客户端的核心是编写任务处理器。您需要在 `handlers.py` 或启动脚本中使用 `@client.on_task` 装饰器注册处理函数。

处理函数可以同步或异步：

```python
from HBPU_Student_Client.client import ArenaClient
from HBPU_Student_Client.models import Task, Answer

client = ArenaClient(student_id="student_001", server_url="ws://localhost:8000")

@client.on_task
def my_task_handler(task: Task) -> Answer:
    # 在这里编写您的逻辑来处理 task.content
    result_text = f"这是我对任务 '{task.content}' 的回答"
    return Answer(content=result_text)

# 或者使用异步函数
@client.on_task
async def my_async_task_handler(task: Task) -> Answer:
    # 异步处理逻辑
    ...
```

### 启动客户端

运行您的客户端脚本（如 `main.py` 或 `example.py`）：

```bash
python main.py
```

客户端启动后会自动连接到服务端，并在收到任务时自动调用您注册的处理器。

## 架构简述

1.  **发布任务:** 管理员/服务端向特定的或所有的 WebSocket 连接广播 Task 数据。
2.  **处理任务:** 客户端接收到 Task，根据类型调用用户注册的 Handler，生成 Answer。
3.  **提交结果:** 客户端将 Answer 通过 WebSocket 发送回服务端。
4.  **评估评分:** 服务端的 `LLMEvaluator` 接收到答案，调用配置好的大语言模型 API 进行评分，并将 Evaluation 结果返回给客户端。
