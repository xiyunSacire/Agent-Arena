"""
HBPU Agent Arena Server - LLM 评分器模块

本模块负责调用大语言模型(LLM)对学生答案进行自动评分。
支持两种运行模式：
- 测试模式：使用本地模拟评分逻辑（开发调试用，已注释）
- 真实模式：调用外部 LLM API 进行评分（生产环境使用）

关键流程说明：
.  websocket.py 收到学生答案 ──→ 调用 evaluate()
.          │
.          ├──→ 【测试模式】本地模拟评分（开发调试）
.          │       └──→ 直接返回预设评分结果
.          │
.          └──→ 【真实模式】调用 LLM API 评分
.                  │
.                  ├──→ 1. 构建评分提示词（包含任务要求、学生答案、评分标准）
.                  │
.                  ├──→ 2. 异步 HTTP POST 请求 → LLM API
.                  │       │
.                  │       ├──→ URL: {LLM_BASE_URL}/v1/chat/completions
.                  │       ├──→ Headers: Authorization Bearer Token
.                  │       └──→ Body: model + messages + temperature(0.1)
.                  │
.                  ├──→ 3. 解析 API 响应
.                  │       │
.                  │       ├──→ 检查 HTTP 状态码（200 = 成功）
.                  │       ├──→ 提取 choices[0].message.content
.                  │       └──→ 解析 content 中的 JSON 数据
.                  │
.                  └──→ 4. 返回 EvaluationResult 对象
.                          │
.                          ├──→ score: 评分分数（0-100）
.                          └──→ reason: 评分理由/评语
.
.  评分结果返回至 websocket.py ──→ 保存数据库 + 发送给学生

评分标准详情：
.  ┌─────────────┬──────┬─────────────────────────┐
.  │     维度       分值         评判标准          
.  ├─────────────┼──────┼─────────────────────────┤
.  │   准确性       40分     答案是否正确，事实准确    
.  │   完整性       30分     是否覆盖所有要点          
.  │   逻辑性       20分     推理是否清晰，条理分明    
.  │   表达         10分     语言是否流畅，表述清晰    
.  └─────────────┴──────┴─────────────────────────┘

异常处理：
.  - HTTP 状态码非 200 → 抛出 RuntimeError
.  - 响应非合法 JSON → 抛出 RuntimeError
.  - 缺少 choices[0].message.content → 抛出 RuntimeError
.  - content 非合法 JSON → 抛出 RuntimeError

作者: Sacire
"""
import json
import httpx
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field
from config import settings

if TYPE_CHECKING:
    from api.websocket import AnswerSubmission
    
# --- Pydantic 数据模型 ---
class EvaluationResult(BaseModel):  
    score: int = Field(..., ge=0, le=100)   # 评分分数，范围 0-100
    reason: str                             # 评分理由/评语
    
class LLMEvaluator:
    """LLM 评分器
    封装 LLM API 调用逻辑，提供统一的评分接口。
    通过异步方式调用外部 LLM 服务，避免阻塞主事件循环。
    """
    async def evaluate(self, task_content: str, student_answer: 'AnswerSubmission') -> EvaluationResult:
        """对学生答案进行评分
        构建评分提示词，调用 LLM API 获取评分结果。
        支持测试模式（本地模拟）和真实 API 调用模式。
        Args:
            task_content: 任务要求/题目内容
            student_answer: 学生提交的答案数据
        Returns:
            EvaluationResult: 包含 score 和 reason 的评分结果
        Raises:
            RuntimeError: 当 LLM API 返回异常或数据格式不正确时
        """
        # ========== 测试模式（开发调试用）==========
        # 取消以下注释可启用本地模拟评分，无需调用外部 API
        # if len(student_answer.final_answer.strip()) > 10:
        #     return EvaluationResult(score=80, reason="答案内容充实")
        # else:
        #     return EvaluationResult(score=60, reason="答案过于简短")

        # ========== API调用 ==========
        prompt = f"""你是一个严格的语言模型评分员，你的任务是为本地大模型的回复进行评分。请根据以下标准评分（0-100分）：
        任务要求：{task_content}
        模型答案：{student_answer.final_answer}
        推理过程：{student_answer.reasoning}
        评分标准：
        1. 准确性（40分）：答案是否正确
        2. 完整性（30分）：是否覆盖所有要点
        3. 逻辑性（20分）：推理是否清晰
        4. 表达（10分）：语言是否流畅
        请以JSON格式返回：{{"score": 整数, "reason": "简短评语"}}"""
        
        # 使用异步 HTTP 客户端调用 LLM API
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = settings.LLM_BASE_URL.rstrip("/") + "/v1/chat/completions"
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1, # 低温度确保评分一致性
                },
            )

            response_text = response.text
            print(f"📦 LLM API response status={response.status_code}")
            print(f"📦 LLM API raw body={response_text}")
            
            # 解析 API 响应
            try:
                result = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"LLM 返回的数据不是合法 JSON: {exc}; status={response.status_code}; body={response_text}"
                )
                
            # 检查 HTTP 状态码
            if response.status_code != 200:
                raise RuntimeError(f"LLM 请求失败: {response.status_code} {result}")

            # 提取 LLM 返回的内容文本
            content_text = (
                result.get("choices", [])
                and result["choices"][0].get("message", {}).get("content")
            )
            if not content_text:
                raise RuntimeError(
                    f"LLM 返回结构不符合预期，缺少 choices[0].message.content: {result}"
                )
                
            # 解析内容文本为 JSON 格式
            try:
                content = json.loads(content_text)
            except Exception as exc:
                raise RuntimeError(
                    f"LLM 返回的 content 不是合法 JSON: {exc}; content={content_text}"
                )

            return EvaluationResult(**content)