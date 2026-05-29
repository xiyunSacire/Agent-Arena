"""
HBPU Agent Student Client - 客户端核心模块

本模块实现了 Agent Student 的 WebSocket 客户端通信框架，负责：
.  管理与竞技场服务器（Arena Server）的长连接及身份认证。
.  接收并解析服务器下发的实时任务（Task）。
.  调度用户定义的任务处理器（Handler），支持同步及异步函数的安全执行。
.  自动化处理心跳保活、断线指数退避重连及任务结果回传。

关键流程说明：
.  【启动与连接流程】
.  执行 client.run() ──→ asyncio.run() 启动异步事件循环
.          │
.          ├──→ 1. 执行 start() 前置校验（确保已注册 @on_task）
.          │
.          ├──→ 2. 进入 _run() 状态机循环
.          │       │
.          │       ├──→ 调用 _connect() 建立 WebSocket 连接
.          │       └──→ 成功后重置重连计数器，初始化心跳时间
.          │
.          └──→ 3. 开启消息监听循环 (async for message in websocket)
.                  │
.                  ├──→ 收到 Task ──→ 调度 _handle_task()
.                  ├──→ 收到 Evaluation ──→ 打印评分结果日志
.                  └──→ 收到 Heartbeat ──→ 更新最后存活时间戳
.
.  【任务处理流程】
.  收到任务数据 ──→ 封装为 Task 模型对象
.          │
.          ├──→ 1. 识别 Handler 类型
.          │       ├──→ 若为 async def: 直接在事件循环中 await
.          │       └──→ 若为普通 def: 投递至 ThreadPool 执行，防止阻塞 I/O
.          │
.          ├──→ 2. 获取处理结果 (Answer 或 dict)
.          │
.          └──→ 3. 序列化结果 ──→ 通过 WebSocket 异步推送到服务端
.
.  【容错与退出流程】
.  连接异常断开 ──→ 触发自动重连机制（根据 RECONNECT_DELAY 等待）
.          │
.          └──→ 达到 MAX_RECONNECT_ATTEMPTS 或捕获退出信号 ──→ 优雅关闭

架构设计说明：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                          ArenaClient (核心)                         │
.  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │
.  │  │   网络通信层    │  │   任务调度层    │  │   容错管理层    │      │
.  │  │ (websockets)    │  │  (Inspection)   │  │ (Auto-Reconnect)│      │
.  │  └─────────────────┘  └─────────────────┘  └─────────────────┘      │
.  └─────────────────────────────────────────────────────────────────────┘
.            ▲                     │                     │
.            │ 发送答案            │ 调用                │ 读取配置
.            ▼                     ▼                     ▼
.    ┌───────────────┐     ┌───────────────┐     ┌───────────────┐
.    │  Arena Server │     │ 用户业务处理器 │     │   config.py   │
.    └───────────────┘     └───────────────┘     └───────────────┘

组件生命周期：
.  [实例化] ──→ 配置 student_id 与服务器地址
.  [注册期] ──→ 使用装饰器 @on_task 绑定业务逻辑函数
.  [运行期] ──→ 建立连接 ──→ 消息循环 (收发) ──→ 异常重连
.  [销毁期] ──→ 捕获 Ctrl+C 或信号 ──→ 发送关闭帧 ──→ 释放循环资源

参数配置说明：
.  ┌──────────────────────┬───────────────────────────────────────────────┐
.  │       参数           │                   说明                        │
.  ├──────────────────────┼───────────────────────────────────────────────┤
.  │ student_id           │ 学生唯一标识，用于身份识别及成绩汇总            │
.  │ server_url           │ 服务器基础 WebSocket 地址                      │
.  │ auto_reconnect       │ 是否在网络抖动时自动尝试恢复连接                │
.  │ show_debug           │ 是否在终端输出详细的实时运行日志                │
.  │ heartbeat_interval   │ 客户端心跳包发送频率（依赖 config 设定）         │
.  └──────────────────────┴───────────────────────────────────────────────┘

作者: Sacire
"""
import asyncio
import json
import time
import signal
import sys
import traceback
import inspect
from typing import Callable, Optional
from datetime import datetime

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from HBPU_Student_Client.config import SERVER_URL, RECONNECT_DELAY, HEARTBEAT_INTERVAL, MAX_RECONNECT_ATTEMPTS
from HBPU_Student_Client.models import Task, Answer


class ArenaClient:
    """    Agent Arena WebSocket 客户端
    
    职责：
    1. 管理与竞技场服务器的 WebSocket 长连接
    2. 接收并解析服务器下发的任务
    3. 调用用户注册的任务处理器执行业务逻辑
    4. 将处理结果（答案）回传至服务器
    5. 处理心跳保活与断线自动重连机制
    
    使用示例：
        app = ArenaClient(student_id="2024001")
        
        @app.on_task
        def handle_task(task: Task) -> Answer:
            return Answer(reasoning="...", final_answer="...")
        
        app.run()
    """
    def __init__(
        self,
        student_id: str,
        server_url: str = SERVER_URL,   
        auto_reconnect: bool = True,    
        show_debug: bool = True,        
    ):
        """
        初始化 Arena 客户端实例
        
        参数:
            student_id: 学生学号，用于服务器端身份识别与成绩记录
            server_url: WebSocket 服务器基础地址，默认为配置文件中的 SERVER_URL
            auto_reconnect: 是否在网络断开时自动尝试重连
            show_debug: 是否在控制台输出调试日志信息
        """
        self.student_id = student_id
        self.server_url = f"{server_url.rstrip('/')}/{student_id}"      # 构建完整的 WebSocket 连接 URL（格式：{base_url}/{student_id}）
        self.auto_reconnect = auto_reconnect                            # 断线自动重连开关
        self.show_debug = show_debug                                    # 调试日志输出开关

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None # WebSocket 连接实例（初始化时为 None）
        self.task_handler: Optional[Callable] = None                        # 用户定义的任务处理回调函数
        self.is_running = False                             # 客户端运行状态标志
        self.reconnect_count = 0                            # 当前重连尝试次数计数器 
        self.last_heartbeat = time.time()                   # 最后一次收到心跳包的时间戳（用于连接活性检测）
        self._shutdown_event = asyncio.Event()              # 异步事件对象，用于协调优雅关闭流程

        # 非 Windows 平台注册信号处理器（SIGINT: Ctrl+C, SIGTERM: 终止信号）
        # Windows 平台信号机制有限，跳过注册以保持兼容性
        if sys.platform != "win32":
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """
        系统信号处理函数（SIGINT / SIGTERM）
        当接收到终止信号时，设置关闭事件标志，触发主循环的优雅退出流程。
        """
        self._log("\n⚠️  检测到退出信号，正在安全关闭...")
        self._shutdown_event.set()

    def on_task(self, func: Callable):
        """
        任务处理器注册装饰器
        
        用法：
            @client.on_task
            def my_task_handler(task: Task) -> Answer:
                ...
        
        参数:
            func: 用户定义的任务处理函数，接收 Task 对象，返回 Answer 或字典
        
        返回:
            原函数（保持函数签名不变）
        """
        self.task_handler = func
        self._log(f"✅ 已注册任务处理器: {func.__name__}")
        return func

    def _log(self, message: str):
        """
        内部调试日志输出方法
        
        仅在 show_debug 为 True 时输出带时间戳的日志信息。
        
        参数:
            message: 要输出的日志内容
        """
        if self.show_debug:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
            
    async def _handle_task(self, task_data: dict):
        """
        处理服务器下发的任务数据

        流程：
        1. 将原始字典数据反序列化为 Task 对象
        2. 调用用户注册的任务处理器执行业务逻辑（安全地处理同步/异步函数）
        3. 将处理结果序列化并通过 WebSocket 回传
        """
        try:
            # 将原始数据转换为结构化 Task 对象
            task = Task(task_data)
            self._log(f"📥 收到任务: {task}")
            # 前置检查：确保任务处理器已注册
            if not self.task_handler:
                self._log("❌ 未注册任务处理器！")
                return

            # 记录任务处理开始时间（用于计算处理耗时）
            start_time = time.time()

            # === 关键修复：安全调用用户处理器 ===
            if inspect.iscoroutinefunction(self.task_handler):
                # 用户注册的是 async def 函数 → 直接 await
                result = await self.task_handler(task)
            else:
                # 用户注册的是 def 函数（同步）→ 放入线程池执行，避免阻塞事件循环
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self.task_handler, task)
            # ===================================

            # 计算任务处理总耗时
            processing_time = time.time() - start_time

            # 2. 构建消息体
            send_data = None
            if isinstance(result, Answer):
                if not result.student_id:
                    result.student_id = self.student_id
                send_data = result.to_dict()
            elif isinstance(result, dict):
                required_fields = ["reasoning", "final_answer"]
                if not all(field in result for field in required_fields):
                    raise ValueError(f"答案格式错误，必需字段: {required_fields}")
                send_data = {
                    "student_id": self.student_id,
                    "task_id": task.task_id,
                    "reasoning": result["reasoning"],
                    "final_answer": result["final_answer"],
                    "tool_used": result.get("tool_used", ""),
                    "timestamp": time.time(),
                }
            else:
                raise TypeError("处理器必须返回 Answer 对象或字典")

            # 3. 发送答案
            if self.websocket and self.websocket.open:
                await self.websocket.send(json.dumps(send_data))
                self._log(f"📤 已提交答案（处理耗时: {processing_time:.2f}s）")
            else:
                self._log(f"⚠️ 连接已断开（状态: {self.websocket.open if self.websocket else '无连接'}），放弃发送答案")

        except Exception as e:
            self._log(f"❌ 处理任务失败: {e}")
            traceback.print_exc()

#----- 修复前的 _handle_task 方法（仅供对比，已在上方修复） -----
    '''
    async def _handle_task(self, task_data: dict):
        """
        处理服务器下发的任务数据
        
        流程：
        1. 将原始字典数据反序列化为 Task 对象
        2. 调用用户注册的任务处理器执行业务逻辑
        3. 将处理结果序列化并通过 WebSocket 回传
        
        参数:
            task_data: 服务器下发的任务原始字典数据
        """
        try:
            # 将原始数据转换为结构化 Task 对象
            task = Task(task_data)
            self._log(f"📥 收到任务: {task}")
            # 前置检查：确保任务处理器已注册
            if not self.task_handler:
                self._log("❌ 未注册任务处理器！")
                return
            # 记录任务处理开始时间（用于计算处理耗时）
            start_time = time.time()

            # 1. 执行耗时任务
            # 调用用户定义的任务处理器（同步或异步均可）
            result = self.task_handler(task)
            # 计算任务处理总耗时
            processing_time = time.time() - start_time

            # 2. 构建消息体
            # 根据处理器返回类型构造发送数据体
            send_data = None
            if isinstance(result, Answer):
                # 若返回 Answer 对象，自动补全 student_id 字段
                if not result.student_id: result.student_id = self.student_id
                send_data = result.to_dict()
            elif isinstance(result, dict):
                # 若返回字典，校验必需字段完整性
                required_fields = ["reasoning", "final_answer"]
                if not all(field in result for field in required_fields):
                    raise ValueError(f"答案格式错误，必需字段: {required_fields}")
                # 构建标准格式的答案数据
                send_data = {
                    "student_id": self.student_id,
                    "task_id": task.task_id,
                    "reasoning": result["reasoning"],
                    "final_answer": result["final_answer"],
                    "tool_used": result.get("tool_used", ""),
                    "timestamp": time.time(),
                }
            else:
                # 返回值类型不符合预期
                raise TypeError("处理器必须返回 Answer 对象或字典")

            # 3. 关键调试点：发送前检查连接状态
            # 发送前确认 WebSocket 连接处于可用状态
            if self.websocket and self.websocket.open:
                await self.websocket.send(json.dumps(send_data))
                self._log(f"📤 已提交答案（处理耗时: {processing_time:.2f}s）")
            else:
                # 连接已断开，放弃本次发送（答案将丢失）
                self._log(f"⚠️ 连接已断开（状态: {self.websocket.open if self.websocket else '无连接'}），放弃发送答案")

        except Exception as e:
            self._log(f"❌ 处理任务失败: {e}")
            traceback.print_exc()
    '''

    async def _handle_message(self, message: str):
        """
        WebSocket 消息分发处理器
        
        根据消息中的 type 字段将消息路由到对应的处理逻辑：
        - "task": 任务消息，调用 _handle_task 处理
        - "evaluation_result": 评分结果消息，输出评分信息
        - "heartbeat": 心跳消息，更新时间戳
        
        参数:
            message: 接收到的原始 JSON 字符串消息
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type", "task")

            if msg_type == "task":
                await self._handle_task(data)
            elif msg_type == "evaluation_result":
                score = data.get("score", 0)
                reason = data.get("reason", "")
                response_time = data.get("response_time", 0)
                self._log(f"⭐ 评分结果: {score}分 - {reason}（响应: {response_time}s）")
            elif msg_type == "heartbeat":
                # 心跳消息 -> 更新最后心跳时间
                self.last_heartbeat = time.time()
            else:
                self._log(f"❓ 未知消息类型: {msg_type}")
        except json.JSONDecodeError:
            self._log(f"⚠️  消息解析失败: {message[:100]}")
        except Exception as e:
            self._log(f"❌ 消息处理错误: {e}")
            traceback.print_exc()

    async def _connect(self) -> bool:
        """
        建立 WebSocket 连接
        
        返回:
            True: 连接成功
            False: 连接失败
        """
        try:
            self._log(f"🔌 正在连接到 {self.server_url}...")
            self.websocket = await websockets.connect(
                self.server_url,
                ping_interval=HEARTBEAT_INTERVAL,       # 心跳发送间隔
                ping_timeout=HEARTBEAT_INTERVAL * 2,    # 心跳响应超时时间
                close_timeout=5,                        # 关闭握手超时时间
            )
            self._log("✅ 连接成功！")
            # 重置重连计数器
            self.reconnect_count = 0
            # 初始化心跳时间戳
            self.last_heartbeat = time.time()
            return True
        except Exception as e:
            self._log(f"❌ 连接失败: {e}")
            return False

    async def _run(self):
        """
        客户端主运行循环
        
        职责：
        1. 建立 WebSocket 连接
        2. 处理断线重连逻辑
        3. 循环接收并处理消息
        4. 响应关闭信号执行优雅退出
        """
        self.is_running = True
        # 主循环：持续尝试建立连接并处理消息
        while self.is_running and not self._shutdown_event.is_set():
            # 尝试建立连接
            if not await self._connect():
                # 连接失败，判断是否需要重试
                if self.auto_reconnect and self.reconnect_count < MAX_RECONNECT_ATTEMPTS:
                    self.reconnect_count += 1
                    self._log(f"⏳ {RECONNECT_DELAY}秒后尝试重连（{self.reconnect_count}/{MAX_RECONNECT_ATTEMPTS}）...")
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
                # 已达最大重试次数或未开启自动重连，退出循环
                break

            try:
                # 消息接收循环：异步迭代 WebSocket 消息流
                async for message in self.websocket:
                    # 检查是否需要退出
                    if self._shutdown_event.is_set():
                        break
                    # 分发消息到处理器
                    await self._handle_message(message)
            except (ConnectionClosed, ConnectionClosedError) as e:
                # WebSocket 连接正常关闭或异常断开
                self._log(f"⚠️ 连接断开: {e}")
                self.websocket = None
                # 判断是否需要重连
                if self.auto_reconnect and self.reconnect_count < MAX_RECONNECT_ATTEMPTS:
                    self.reconnect_count += 1
                    self._log(f"⏳ {RECONNECT_DELAY}秒后尝试重连（{self.reconnect_count}/{MAX_RECONNECT_ATTEMPTS}）...")
                    await asyncio.sleep(RECONNECT_DELAY)
                else:
                    break
            except Exception as e:
                # 其他未预期的运行时异常
                self._log(f"❌ 运行时错误: {e}")
                traceback.print_exc()
                break
        
        # 清理工作
        self.is_running = False
        if self.websocket:
            await self.websocket.close()
        self._log("👋 客户端已停止")

    async def start(self):
        """
        异步启动客户端
        
        在启动前进行必要的检查，然后进入主运行循环。
        
        异常:
            RuntimeError: 未注册任务处理器时抛出
        """
        # 前置检查：确保任务处理器已注册
        if not self.task_handler:
            raise RuntimeError("请先使用 @app.on_task 装饰器注册任务处理器！")
        
        # 输出启动信息
        self._log("=" * 60)
        self._log("🎓 HBPU Agent Arena Client 启动")
        self._log(f"👤 学号: {self.student_id}")
        self._log(f"📡 服务器: {self.server_url}")
        self._log(f"🔄 自动重连: {'开启' if self.auto_reconnect else '关闭'}")
        self._log("=" * 60)
        
        # 进入主运行循环
        await self._run()

    def run(self):
        """
        同步方式启动客户端（阻塞调用）
        
        封装 asyncio.run() 以简化调用方式，同时处理常见的异常场景。
        适用于脚本直接运行的场景。
        """
        try:
            # 使用 asyncio.run() 启动异步主循环
            asyncio.run(self.start())
        except KeyboardInterrupt:
            # 用户主动中断（Ctrl+C）
            self._log("\n👋 检测到Ctrl+C，正在退出...")
        except Exception as e:
            # 其他未捕获的异常
            self._log(f"❌ 启动失败: {e}")
            traceback.print_exc()
