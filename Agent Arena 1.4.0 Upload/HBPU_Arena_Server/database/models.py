"""
HBPU Agent Arena Server - SQLAlchemy 数据模型模块

本模块定义所有数据库表结构，使用 SQLAlchemy ORM 进行对象关系映射。
包含学生信息表和成绩记录表两个核心实体。

数据模型：
- Student: 学生信息表，存储学生基本信息和在线状态
- Score: 成绩记录表，存储学生答题评分结果

关系说明：
- Student 与 Score 为一对多关系
- 级联删除：删除学生时自动删除关联的所有成绩记录

关键流程说明：
.  学生客户端 WebSocket 连接 ──→ ConnectionManager.connect()
.          │
.          └──→ 查询或创建 Student 记录
.                  │
.                  ├──→ 学生已存在 → 更新 last_online 时间
.                  │
.                  └──→ 新学生 → 创建 Student 记录 + 设置默认姓名
.
.  学生提交答案 ──→ websocket.py 接收并评分
.          │
.          ├──→ LLMEvaluator.evaluate() 获取评分结果
.          │
.          └──→ _save_answer() 保存到数据库
.                  │
.                  ├──→ 1. 查询或创建 Student 记录（确保外键存在）
.                  │
.                  ├──→ 2. 创建 Score 记录
.                  │       │
.                  │       ├──→ student_id: 关联学生
.                  │       ├──→ task_id: 关联任务
.                  │       ├──→ score: 评分分数
.                  │       ├──→ reason: 评分评语
.                  │       ├──→ answer_content: 学生答案
.                  │       └──→ response_time: 响应耗时
.                  │
.                  └──→ 3. 提交事务（db.commit()）
.
.  管理员查询成绩 ──→ admin.py 路由
.          │
.          ├──→ 查询所有学生 → SELECT * FROM students
.          │
.          ├──→ 查询单个学生成绩 → SELECT * FROM scores WHERE student_id = ?
.          │
.          └──→ 通过 Student.scores 关系属性访问关联成绩

表结构说明：
.  ┌─────────────────────────────────────────────────────────────┐
.  │                      students 表                             │
.  ├─────────────┬──────────────┬────────────────────────────────┤
.  │   字段名     │    类型       │           说明                 │
.  ├─────────────┼──────────────┼────────────────────────────────┤
.  │ student_id  │ VARCHAR(20)  │ 主键，学生唯一标识              │
.  │ name        │ VARCHAR(50)  │ 学生姓名                        │
.  │ last_online │ DATETIME     │ 最后在线时间（UTC）             │
.  └─────────────┴──────────────┴────────────────────────────────┘
.
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                           scores 表                                   │
.  ├───────────────┬──────────────┬──────────────────────────────────────┤
.  │    字段名      │    类型       │                说明                  │
.  ├───────────────┼──────────────┼──────────────────────────────────────┤
.  │ id            │ INTEGER      │ 主键，自增                            │
.  │ student_id    │ VARCHAR(20)  │ 外键，关联 students.student_id        │
.  │ task_id       │ VARCHAR(50)  │ 任务ID，带索引                        │
.  │ score         │ INTEGER      │ 评分分数                              │
.  │ reason        │ TEXT         │ 评分理由/评语                         │
.  │ answer_content│ TEXT         │ 学生提交的答案内容                     │
.  │ response_time │ FLOAT        │ 响应耗时（秒）                        │
.  │ submitted_at  │ DATETIME     │ 提交时间（UTC）                       │
.  └───────────────┴──────────────┴──────────────────────────────────────┘

关系映射：
.  Student.scores    ←──→ Score.student
.       ↑                      ↑
.   (一对多)                (多对一)
.       级联删除：删除学生时自动删除其所有成绩记录

作者: Sacire
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# 创建 SQLAlchemy 基类，所有模型类都继承自此类
Base = declarative_base()

class Student(Base):
    """学生信息表
    存储学生的基本信息，包括学生ID、姓名、最后在线时间等。
    与 Score 表建立一对多关系。
    """
    __tablename__ = "students"
    student_id = Column(String(20), primary_key=True, index=True)       # 学生唯一标识，主键，索引
    name = Column(String(50))                                           # 学生姓名
    last_online = Column(DateTime, default=datetime.utcnow)             # 最后在线时间，默认当前UTC时间
    scores = relationship("Score", back_populates="student", cascade="all, delete-orphan")      # 关联的成绩记录，级联删除

class Score(Base):
    """成绩记录表
    
    存储学生的答题评分结果，包括分数、评语、答案内容、响应时间等。
    通过外键关联到 Student 表。
    """
    __tablename__ = "scores"
    
    id = Column(Integer, primary_key=True, autoincrement=True)              # 记录唯一标识，自增主键
    student_id = Column(String(20), ForeignKey("students.student_id"))      # 学生外键，关联 students 表
    task_id = Column(String(50), index=True)                                # 任务唯一标识，索引加速查询
    score = Column(Integer)                                                 # 评分分数
    reason = Column(Text)                                                   # 评分理由/评语
    answer_content = Column(Text)                                           # 学生提交的答案内容
    response_time = Column(Float)                                           # 响应耗时（秒）
    submitted_at = Column(DateTime, default=datetime.utcnow)                # 提交时间，默认当前UTC时间
    
    student = relationship("Student", back_populates="scores")              # 关联的学生对象