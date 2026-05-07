"""
HBPU Agent Arena Server - 管理端 API 路由

本模块负责处理管理端的所有业务逻辑，包括：
.  发布竞赛任务并广播至所有在线客户端。
.  查询实时在线的学生列表及统计信息。
.  检索特定任务的评分详情。
.  生成并返回学生总分排行榜。

关键流程说明：
.  【发布任务流程】
.  管理员 POST /admin/publish_task ──→ 接收任务发布请求
.          │
.          ├──→ 1. 验证是否有在线学生
.          │       └──→ 无在线学生 → 返回 400 错误
.          │
.          ├──→ 2. 构建任务报文（添加 timestamp 时间戳）
.          │
.          ├──→ 3. 调用 ConnectionManager.broadcast_task()
.          │       │
.          │       ├──→ 任务存入内存缓存（供评分时查询）
.          │       │
.          │       └──→ 并发发送给所有在线学生 WebSocket
.          │
.          └──→ 4. 返回广播结果（成功状态 + 接收人数）
.
.  【查询在线学生流程】
.  管理员 GET /admin/online_students ──→ 获取实时在线状态
.          │
.          ├──→ 从 ConnectionManager.active_connections 获取映射表
.          │
.          └──→ 返回在线人数 + 学生 ID 列表
.
.  【查询任务评分流程】
.  管理员 GET /admin/scores/{task_id} ──→ 查询指定任务的所有评分
.          │
.          ├──→ 数据库查询: SELECT * FROM scores WHERE task_id = ?
.          │
.          └──→ 返回 ScoreResponse 列表（学号、分数、评语、响应时间）
.
.  【查询排行榜流程】
.  管理员 GET /admin/rankings ──→ 生成学生总分排行榜
.          │
.          ├──→ 1. 数据库聚合查询
.          │       │
.          │       ├──→ JOIN students 与 scores 表
.          │       ├──→ GROUP BY student_id
.          │       ├──→ SUM(score) AS total_score
.          │       ├──→ COUNT(score.id) AS task_count
.          │       └──→ ORDER BY total_score DESC
.          │
.          └──→ 2. 返回排行榜数据（学号、姓名、总分、任务数）

API 端点总览：
.  ┌────────────┬─────────────────────────┬────────────────────────────────┐
.  │  方法       │        端点              │             说明                │
.  ├────────────┼─────────────────────────┼────────────────────────────────┤
.  │ POST       │ /admin/publish_task     │ 发布任务并广播给所有在线学生     │
.  │ GET        │ /admin/online_students  │ 获取当前在线学生列表及人数       │
.  │ GET        │ /admin/scores/{task_id} │ 查询指定任务的所有评分记录       │
.  │ GET        │ /admin/rankings         │ 获取学生总分排行榜               │
.  └────────────┴─────────────────────────┴────────────────────────────────┘

数据流向示意：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                          管理员客户端                                 │
.  └─────────────────────────────────────────────────────────────────────┘
.                    │                                              │
.                    │ POST /publish_task                           │ GET /rankings
.                    ▼                                              ▼
.  ┌─────────────────────────────────┐          ┌─────────────────────────────────┐
.  │        ConnectionManager         │          │          数据库层                 │
.  │  ┌───────────────────────────┐  │          │  ┌───────────────────────────┐  │
.  │  │   active_connections      │  │          │  │   students 表             │  │
.  │  │   {student_id: websocket} │  │          │  │   scores 表               │  │
.  │  └───────────────────────────┘  │          │  └───────────────────────────┘  │
.  │  ┌───────────────────────────┐  │          │                                 │
.  │  │   tasks 缓存              │  │          │                                 │
.  │  │   {task_id: task_data}    │  │          │                                 │
.  │  └───────────────────────────┘  │          │                                 │
.  └─────────────────────────────────┘          └─────────────────────────────────┘
.                    │                                              ▲
.                    │ WebSocket 广播                                │ SQL 查询
.                    ▼                                              │
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                        学生客户端群                                   │
.  │   (student_001)  (student_002)  (student_003)  ...                   │
.  └─────────────────────────────────────────────────────────────────────┘

作者: Sacire
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import Student, Score
from pydantic import BaseModel
from typing import List
import time
from sqlalchemy import func

# --- 路由配置 ---
router = APIRouter(prefix="/admin", tags=["Admin"])

# --- Pydantic 数据模型 (用于 API 请求与响应) ---
class TaskPublishRequest(BaseModel):
    """任务发布请求模型"""
    task_id: str      # 任务唯一标识
    task_type: str    # 任务类型 (例如: 'coding', 'qa')
    content: str      # 任务具体内容或提示词
    timeout_sec: int = 120  # 任务限时（秒），默认为 120
    max_score: int = 100   # 任务总分，默认为 100

class ScoreResponse(BaseModel):
    """评分响应模型"""
    student_id: str
    score: int
    reason: str        # 评分理由或反馈
    response_time: float # 响应耗时
    class Config:
        from_attributes = True # 兼容 SQLAlchemy 模型自动转换 (Pydantic v2 用法)

# --- 管理端接口实现 ---
@router.post("/publish_task")
async def publish_task(task: TaskPublishRequest, request: Request):
    """
    发布新任务
    从全局应用状态中获取 ConnectionManager 实例，将任务广播给所有已连接的学生客户端。
    """
    manager = request.app.state.manager
    
    # 检查是否有活跃连接，避免空广播
    if not manager.active_connections:
        raise HTTPException(status_code=400, detail="当前无在线学生，无法发布任务")
    
    # 构建下发给客户端的任务报文
    task_response = {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "content": task.content,
        "timeout_sec": task.timeout_sec,
        "timestamp": time.time() # 标记发布时间戳，用于客户端计算剩余时间
    }
    
    # 执行 WebSocket 全局广播
    await manager.broadcast_task(task_response)
    
    return {
        "status": "success",
        "task_id": task.task_id,
        "broadcast_count": len(manager.active_connections)
    }

@router.get("/online_students")
async def get_online_students(request: Request):
    """
    获取当前在线学生列表
    通过 ConnectionManager 维护的映射表返回在线学生的 ID。
    """
    manager = request.app.state.manager
    
    return {
        "count": len(manager.active_connections),
        "students": list(manager.active_connections.keys())
    }

@router.get("/scores/{task_id}", response_model=List[ScoreResponse])
async def get_task_scores(task_id: str, db: Session = Depends(get_db)):
    """
    获取指定任务的评分记录
    从数据库中查询所有提交了该任务编号的评分结果。
    """
    scores = db.query(Score).filter(Score.task_id == task_id).all()
    return scores

@router.get("/rankings")
async def get_rankings(db: Session = Depends(get_db)):
    """
    获取排行榜
    基于数据库进行聚合查询：
    1. 关联 Student 和 Score 表。
    2. 按学生 ID 分组。
    3. 计算总分和参与任务的总数。
    4. 按总分降序排列。
    """
    rankings = (
        db.query(
            Student.student_id,
            Student.name,
            func.sum(Score.score).label("total_score"),
            func.count(Score.id).label("task_count")
        )
        .join(Score)
        .group_by(Student.student_id)
        .order_by(func.sum(Score.score).desc())
        .all()
    )
    
    return {
        "rankings": [
            {
                "student_id": item.student_id,
                "name": item.name,
                "total_score": item.total_score,
                "task_count": item.task_count,
            }
            for item in rankings
        ]
    }