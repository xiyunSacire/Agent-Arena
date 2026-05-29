"""
HBPU Agent Arena Server - WebSocket 路由模块

本模块负责处理学生客户端的 WebSocket 连接和答案评分流程，核心功能包括：
.  建立并维护 WebSocket 长连接，管理学生在线状态。
.  接收学生提交的答案数据，解析为结构化对象。
.  将评分任务提交至后台异步执行，避免阻塞消息接收循环。
.  调用 LLM 评分器对学生答案进行智能评估。
.  将评分结果持久化到数据库，并实时返回给学生客户端。

关键流程说明：
.  学生客户端 ──WebSocket连接──→ /ws/{student_id}
.          │
.          └──→ 提交答案（JSON格式）
.                  │
.                  ├──→ 解析为 AnswerSubmission 对象
.                  │
.                  ├──→ 创建后台异步任务（不阻塞消息接收）
.                  │       │
.                  │       ├──→ 调用 LLM 评分器评分
.                  │       │
.                  │       ├──→ 保存成绩到数据库
.                  │       │
.                  │       └──→ 通过 WebSocket 返回评分结果
.                  │
.                  └──→ 继续接收下一条消息

作者: Sacire
"""
import asyncio
import time
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from database.session import SessionLocal
from database.models import Score, Student

# 创建 WebSocket 路由对象
router = APIRouter()

# ==================== Pydantic 数据模型 ====================
class AnswerSubmission(BaseModel):
    student_id: str
    task_id: str
    reasoning: str
    final_answer: str
    tool_used: Optional[str] = None
    timestamp: Optional[float] = None

# ==================== 数据保存函数 ====================
def _save_answer(answer: AnswerSubmission, evaluation):
    """
    将学生答案和评分结果保存到数据库
    
    参数:
        answer: 学生提交的答案数据
        evaluation: LLM 评分器返回的评分结果对象
    """
    db = SessionLocal() # 创建数据库会话
    try:
        # 查找或创建学生记录
        student = db.query(Student).filter(Student.student_id == answer.student_id).first()
        if not student:
            # 学生不存在则自动创建
            student = Student(student_id=answer.student_id, name=f"学生_{answer.student_id}")
            db.add(student)

        # 创建成绩记录
        score_record = Score(
            student_id=answer.student_id,   # 学号
            task_id=answer.task_id,         # 任务ID
            score=evaluation.score,         # 评分分数
            reason=evaluation.reason,       # 评分理由
            answer_content=answer.final_answer,     # 学生答案内容
            response_time=round(time.time() - (answer.timestamp or time.time()), 2)     # 响应时间（秒）
        )
        db.add(score_record)
        db.commit() # 提交事务
    finally:
        db.close()  # 确保数据库连接关闭

# ==================== 答案处理函数 ====================
async def process_answer(answer: AnswerSubmission, evaluator, manager):
    """
    异步处理学生提交的答案（评分 + 保存 + 返回结果）
    
    参数:
        answer: 学生提交的答案数据
        evaluator: LLM 评分器实例
        manager: WebSocket 连接管理器实例
    """
    answer_timestamp = answer.timestamp or time.time()  # 答案时间戳，未提供则使用当前时间
    start_time = time.time()    # 记录处理开始时间
    try:
        response_time = start_time - answer_timestamp   # 计算响应时间（从提交到开始处理的耗时）

        # 获取原始任务内容（用于评分对比）
        task_data = manager.get_task(answer.task_id)
        if not task_data:
            raise ValueError(f"Task {answer.task_id} not found")
        task_content = task_data.get("content", "")
        
        # 调用 LLM 评分器进行评分
        evaluation = await evaluator.evaluate(task_content, answer)
        
        print(f"🧠 使用任务内容: {task_content}")
        print(f"⭐ 学生 {answer.student_id} 任务 {answer.task_id} 评分: {evaluation.score}分 - {evaluation.reason}")

        # 异步保存评分结果到数据库（在线程池中执行，避免阻塞事件循环）
        await asyncio.to_thread(_save_answer, answer, evaluation)

        # 如果学生仍然在线，发送评分结果
        if answer.student_id in manager.active_connections:
            result_msg = {
                "type": "evaluation_result",    # 消息类型：评分结果
                "task_id": answer.task_id,      # 任务ID
                "score": evaluation.score,      # 评分分数
                "reason": evaluation.reason,    # 评分理由
                "response_time": round(response_time, 2)    # 响应时间（保留2位小数）
            }
            # 通过 WebSocket 发送 JSON 格式的评分结果
            await manager.active_connections[answer.student_id].send_json(result_msg)
            print(f"📤 已发送评分结果给学生 {answer.student_id}")
    except Exception as e:
        print(f"❌ 处理答案失败: {e}")

# ==================== 后台任务异常处理 ====================
def _handle_background_exception(task: asyncio.Task):
    """
    处理后台异步任务的异常（防止静默失败）
    
    参数:
        task: 已完成的异步任务对象
    """
    if task.cancelled():    # 任务被取消则跳过
        return
    exc = task.exception()  # 获取任务抛出的异常
    if exc is not None:
        print(f"❌ 后台任务异常: {exc}")

# ==================== WebSocket 端点 ====================
@router.websocket("/ws/{student_id}")
async def websocket_endpoint(websocket: WebSocket, student_id: str):
    """
    WebSocket 连接端点，处理学生客户端的连接和消息
    
    路径参数:
        student_id: 学生学号，从 URL 路径中提取
    
    工作流程:
        1. 接受 WebSocket 连接
        2. 循环接收学生提交的答案
        3. 将评分任务提交到后台异步执行（不阻塞消息接收）
        4. 连接断开时清理资源
    """
    # 从 FastAPI app.state 中获取全局共享的管理器和评分器实例
    manager = websocket.app.state.manager
    evaluator = websocket.app.state.evaluator
    # 建立连接，将学生加入活跃连接池
    await manager.connect(websocket, student_id)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"📨 收到学生 {student_id} 的答案: {data[:100]}...")
            answer = AnswerSubmission.parse_raw(data)
            task = asyncio.create_task(process_answer(answer, evaluator, manager))
            task.add_done_callback(_handle_background_exception)
    except WebSocketDisconnect:
        await manager.disconnect(student_id, websocket)
    except Exception as e:
        print(f"❌ WebSocket 错误: {e}")
        await manager.disconnect(student_id, websocket)