"""
HBPU Agent Student Client - 数据模型定义模块

本模块定义了客户端与服务器交互的核心数据结构。
主要职责包括：
.  封装服务器下发的任务信息 (Task)。
.  封装学生提交的回答信息 (Answer)。
.  提供标准化的数据序列化方法 (to_dict)，确保 WebSocket 传输数据的格式一致性。

关键流程说明：
.  【任务接收流程】
.  接收 JSON 数据 ──→ 实例化 Task 对象
.          │
.          ├──→ 提取 task_id, task_type, content
.          ├──→ 设置超时时间 (timeout_sec)
.          └──→ 记录接收时间戳 (timestamp)
.
.  【答案构建流程】
.  处理完成逻辑 ──→ 实例化 Answer 对象
.          │
.          ├──→ 关联 task_id (确保回答对应正确的任务)
.          ├──→ 填充 reasoning (思维链/思考过程)
.          ├──→ 填充 final_answer (最终结论)
.          ├──→ 标记 tool_used (使用的工具，如 Ollama, Calculator)
.          └──→ 记录提交时间戳 (timestamp)
.
.  【数据序列化流程】
.  准备发送数据 ──→ 调用 Answer.to_dict()
.          │
.          └──→ 过滤空值字段 (如 student_id 为空时不发送)
.          └──→ 返回标准字典 ──→ 转为 JSON 字符串发送

架构设计说明：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                          models.py (数据层)                         │
.  │  ┌─────────────────┐                        ┌─────────────────┐    │
.  │  │ Task (输入)     │                        │ Answer (输出)   │    │
.  │  │ - task_id       │                        │ - reasoning     │    │
.  │  │ - content       │                        │ - final_answer  │    │
.  │  │ - timeout       │                        │ - tool_used     │    │
.  │  └─────────────────┘                        └─────────────────┘    │
.  └──────────────────────────────────┬──────────────────────────────────┘
.                                     │ 数据流转
.                                     ▼
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                     client.py (通信层)                              │
.  │  ┌───────────────────────────────────────────────────────────────┐  │
.  │  │                ArenaClient (WebSocket)                        │  │
.  │  └───────────────────────────────────────────────────────────────┘  │
.  └─────────────────────────────────────────────────────────────────────┘

组件生命周期：
.  [实例化] ──→ 接收到原始数据 (dict) ──→ 创建类实例
.  [使用期] ──→ 业务逻辑层读取 Task 属性 / 填充 Answer 属性
.  [序列化] ──→ 调用 to_dict() 转换为可传输格式

属性配置说明：
.  ┌──────────────────────┬───────────────────────────────────────────────┐
.  │       属性           │                   说明                        │
.  ├──────────────────────┼───────────────────────────────────────────────┤
.  │ task_id              │ 任务唯一标识符，用于关联请求与响应            │
.  │ task_type            │ 任务类型 (如 text, math, code)                │
.  │ content              │ 任务的具体文本内容                            │
.  │ timeout_sec          │ 任务处理的最大允许时间 (秒)                   │
.  │ reasoning            │ 模型的思考过程，用于展示思维链                │
.  │ final_answer         │ 最终提交给服务器的答案文本                    │
.  │ tool_used            │ 标记使用的工具名称，便于后端统计与审计        │
.  └──────────────────────┴───────────────────────────────────────────────┘

作者: Sacire
"""
import time
from typing import Optional


class Task:
    """
    接收到的任务对象
    初始化任务对象
    Args:
        data: 包含任务信息的字典，可包含以下字段：
            - task_id: 任务唯一标识符
            - task_type: 任务类型（如数学、编程等）
            - content: 任务的具体内容描述
            - timeout_sec: 任务超时时间（秒），默认60秒
            - timestamp: 任务创建时间戳，默认当前时间
    """
    def __init__(self, data: dict):
        self.task_id: str = data.get("task_id", "")
        self.task_type: str = data.get("task_type", "")
        self.content: str = data.get("content", "")
        self.timeout_sec: int = data.get("timeout_sec", 60)
        self.timestamp: float = data.get("timestamp", time.time())

    def __repr__(self):
        """返回任务的字符串表示，便于调试和日志记录"""
        return f"Task(id={self.task_id}, type={self.task_type}, timeout={self.timeout_sec}s)"


class Answer:
    """学生提交的答案对象"""
    def __init__(
        self,
        task_id: str,
        reasoning: str,
        final_answer: str,
        tool_used: Optional[str] = None,
        student_id: Optional[str] = None,
    ):
        """
        初始化答案对象

        Args:
            task_id: 对应的任务ID
            reasoning: 学生的推理过程或解题思路
            final_answer: 学生的最终答案
            tool_used: 解题过程中使用的工具名称（可选）
            student_id: 提交答案的学生ID（可选）
        """
        self.task_id = task_id
        self.reasoning = reasoning
        self.final_answer = final_answer
        self.tool_used = tool_used or ""
        self.student_id = student_id
        self.timestamp = time.time()        # 答案提交时间戳（自动记录当前时间）

    def to_dict(self) -> dict:
        """
        将答案对象转换为字典格式

        Returns:
            包含所有答案信息的字典，便于JSON序列化或存储
            - 始终包含：task_id, reasoning, final_answer, tool_used, timestamp
            - 仅当student_id存在时才包含该字段
        """
        result = {
            "task_id": self.task_id,
            "reasoning": self.reasoning,
            "final_answer": self.final_answer,
            "tool_used": self.tool_used,
            "timestamp": self.timestamp,
        }
        # 仅当student_id不为None时才添加到结果字典中
        if self.student_id:
            result["student_id"] = self.student_id
        return result
