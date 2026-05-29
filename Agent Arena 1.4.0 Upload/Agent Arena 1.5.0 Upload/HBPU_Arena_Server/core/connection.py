"""
HBPU Agent Arena Server - WebSocket 连接管理模块

本模块负责管理所有活跃的 WebSocket 连接，提供连接生命周期管理、
任务广播、学生状态维护等核心功能。

核心功能：
- 学生连接管理：接受新连接、维护连接映射、处理断开连接
- 任务广播：向单个学生或所有在线学生发送任务
- 任务存储：在内存中缓存任务数据，供评分时查询
- 学生状态同步：更新学生在线状态到数据库

关键流程说明：
.  管理员发布任务 ──→ 调用 broadcast_task()
.          │
.          ├──→ 任务存储到内存缓存（供评分时查询）
.          │
.          └──→ 并发广播给所有在线学生
.                  │
.                  └──→ 每个学生 WebSocket 连接接收任务
.
.  学生客户端 ──WebSocket连接──→ connect()
.          │
.          ├──→ 接受连接，注册到活跃映射表
.          │
.          ├──→ 记录连接时间戳
.          │
.          └──→ 异步更新数据库在线状态
.
.  学生答案到达（在 websocket.py 中处理）──→ 需要查询任务内容
.          │
.          └──→ 调用 get_task() 从内存缓存获取任务数据
.
.  学生断开连接 ──→ disconnect()
.          │
.          ├──→ 从活跃映射表移除
.          │
.          ├──→ 清理时间戳记录
.          │
.          └──→ 关闭 WebSocket 连接

数据结构说明：
.  active_connections      = {student_id: websocket}     # 活跃连接映射
.  connection_timestamps   = {student_id: connect_time}  # 连接时间记录
.  tasks                   = {task_id: task_data}        # 任务内存缓存

作者: Sacire
"""

import asyncio
from fastapi import WebSocket
from typing import Dict
from database.session import SessionLocal
from database.models import Student
from datetime import datetime
import time

class ConnectionManager:
    """WebSocket 连接管理器
    
    管理所有活跃的 WebSocket 连接，维护学生在线状态，
    提供任务广播和点对点消息发送功能。
    """
    def __init__(self):
        """初始化连接管理器
        
        创建三个内部字典用于存储：
        - active_connections: 活跃连接映射 {student_id: websocket}
        - connection_timestamps: 连接时间戳 {student_id: connect_time}
        - tasks: 任务缓存 {task_id: task_data}
        """
        self.active_connections: Dict[str, WebSocket] = {} # {student_id: websocket}
        self.connection_timestamps: Dict[str, float] = {}  # {student_id: connect_time}
        self.tasks: Dict[str, dict] = {} # {task_id: task_data}

    async def connect(self, websocket: WebSocket, student_id: str):
        """接受新的 WebSocket 连接
        
        接受连接请求，注册到活跃连接映射表，
        并更新学生的在线状态到数据库。
        
        Args:
            websocket: FastAPI WebSocket 对象
            student_id: 学生唯一标识符
        """
        await websocket.accept()
        self.active_connections[student_id] = websocket
        self.connection_timestamps[student_id] = time.time()
        await asyncio.to_thread(self._update_student_online, student_id)

    def _update_student_online(self, student_id: str):
        """更新学生在线状态（内部方法）
        
        在后台线程中执行数据库操作，查询或创建学生记录，
        并更新最后在线时间。
        
        Args:
            student_id: 学生唯一标识符
        """
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.student_id == student_id).first()
            if not student:
                student = Student(student_id=student_id, name=f"学生_{student_id}")
                db.add(student)
            student.last_online = datetime.utcnow()
            db.commit()
            print(f"✅ 学生 {student_id} 已连接（当前在线: {len(self.active_connections)}人）")
        finally:
            db.close()

    async def disconnect(self, student_id: str, websocket: WebSocket | None = None):
        """断开 WebSocket 连接
        
        从活跃连接映射表中移除指定学生，关闭 WebSocket 连接，
        并清理相关状态。
        
        Args:
            student_id: 学生唯一标识符
            websocket: WebSocket 对象（可选，用于指定要关闭的连接）
        """        
        if websocket is None:
            websocket = self.active_connections.get(student_id)
        self.active_connections.pop(student_id, None)
        self.connection_timestamps.pop(student_id, None)
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass
        print(f"❌ 学生 {student_id} 已断开（当前在线: {len(self.active_connections)}人）")

    async def send_task(self, student_id: str, task: Dict):
        """向指定学生发送任务
        
        将任务数据以 JSON 格式发送给指定学生。
        如果发送失败，自动断开该学生的连接。
        
        Args:
            student_id: 目标学生唯一标识符
            task: 任务数据字典
        """
        if student_id in self.active_connections:
            try:
                await self.active_connections[student_id].send_json(task)
                print(f"📤 任务 {task.get('task_id')} 已发送给 {student_id}")
            except Exception as e:
                print(f"⚠️ 发送任务失败 {student_id}: {e}")
                self.disconnect(student_id)

    async def broadcast_task(self, task: Dict):
        """向所有在线学生广播任务
        
        先将任务存储到内存缓存，然后并发发送给所有在线学生。
        使用 asyncio.gather 实现并发发送，提高广播效率。
        
        Args:
            task: 任务数据字典
        """
        self.store_task(task)   # 将任务存储在内存中，方便后续查询和评估
        tasks = [self.send_task(student_id, task) for student_id in self.active_connections.keys()]
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"📢 任务 {task.get('task_id')} 已广播（接收者: {len(self.active_connections)}人）")

    def store_task(self, task: dict):
        """将任务存储到内存缓存
        用于评分时查询任务内容。
        Args:  task: 任务数据字典
        """
        task_id = task.get("task_id")
        if task_id:
            self.tasks[task_id] = task

    def get_task(self, task_id: str):
        """从内存缓存获取任务
        评分时调用此方法获取任务内容。
        Args:
            task_id: 任务唯一标识符
        Returns:
            dict: 任务数据字典，如果不存在返回 None
        """
        return self.tasks.get(task_id)