"""
HBPU Agent Student Client - Ollama 本地模型接入示例

本模块演示了如何通过 ArenaClient 接入本地部署的 Ollama 模型服务。
主要职责包括：
.  配置本地 Ollama 服务的连接参数（地址、模型名称、超时时间）。
.  构建适配本地模型的 Prompt 提示词模板。
.  支持可选的 RAG（检索增强生成）功能，通过查询外部知识库提升答案准确度。
.  实现智能答案提取逻辑，支持从 'response' 或 'thinking' 字段中解析结果。
.  自动化记录完整的 API 交互日志（answer.txt），便于调试与分析。

关键流程说明：
.  【初始化与配置流程】
.  脚本启动 ──→ 加载 Ollama 配置 (URL, Model, Timeout)
.          │
.          └──→ 定义业务函数
.                  ├──→ build_local_prompt(): 格式化任务内容（含条件 RAG 增强）
.                  ├──→ extract_answer_from_thinking(): 正则/关键词匹配提取答案
.                  └──→ 接收用户选择，配置全局开关 USE_RAG_ENHANCEMENT

.  【任务执行流程】
.  收到服务器任务 ──→ 触发 @test_app.on_task 装饰的 test_handler
.          │
.          ├──→ 1. 调用 generate_local_answer(task)
.          │       ├──→ [RAG] 若启用，则调用 custom_rag_function() 获取参考上下文
.          │       ├──→ 构建 Prompt (融合任务内容与 RAG 知识)
.          │       ├──→ 构造 Payload (关闭流式, 设置 Temperature)
.          │       ├──→ POST 请求 Ollama API (/api/generate)
.          │       ├──→ [调试] 保存完整 JSON 响应至 answer.txt
.          │       └──→ 解析 JSON (优先 response, 其次 thinking)
.          │
.          ├──→ 2. 处理返回结果
.          │       ├──→ 若 response 为空且存在 thinking ──→ 调用提取函数
.          │       └──→ 返回最终文本
.          │
.          └──→ 3. 封装 Answer
.                  └──→ 返回字典 {reasoning, final_answer, tool_used} ──→ 回传服务器

.  【答案提取策略】
.  输入文本 ──→ 检查 "Answer:" 标记 ──→ 检查 "Final Answer:" 标记
.          │
.          ├──→ 检查计算关键词 (等于, 结果是)
.          │
.          └──→ 兜底策略: 返回原始文本

架构设计说明：
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                       example.py (业务层)                           │
.  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐            │
.  │  │ 提示词构建器  │  │  Ollama 调用  │  │ 结果提取器    │            │
.  │  │ (Prompt Build)│  │ (httpx Client)│  │ (Extractor)   │            │
.  │  └───────────────┘  └───────────────┘  └───────────────┘            │
.  │  ┌─────────────────────────────────────────────────────────┐        │
.  │  │  RAG 增强模块 (当 USE_RAG_ENHANCEMENT = True 时激活)    │        │
.  │  └─────────────────────────────────────────────────────────┘        │
.  └──────────────────────────────────────────┬──────────────────────────┘
.                                             │ 调用/返回
.                                             ▼
.  ┌─────────────────────────────────────────────────────────────────────┐
.  │                     HBPU_Student_Client (框架层)                    │
.  │  ┌───────────────────────────────────────────────────────────────┐  │
.  │  │                   ArenaClient (WebSocket)                     │  │
.  │  └───────────────────────────────────────────────────────────────┘  │
.  └──────────────────────────────────────────┬──────────────────────────┘
.                                             │ 网络通信
.                                             ▼
.                                    ┌───────────────┐
.                                    │  Local Ollama │
.                                    │  (11434)      │
.                                    └───────────────┘

组件生命周期：
.  [配置期] ──→ 定义 OLLAMA_SERVER_URL、MODEL 名称，导入 RAG 函数
.  [运行期] ──→ 实例化 ArenaClient ──→ 用户选择是否启用 RAG ──→ 注册 test_handler
.  [交互期] ──→ 循环接收任务 ──→ 根据 RAG 开关增强提示词 ──→ 调用本地模型 ──→ 提交答案
.  [调试期] ──→ 每次请求生成 answer.txt 记录详细交互数据

参数配置说明：
.  ┌──────────────────────┬───────────────────────────────────────────────┐
.  │       参数           │                   说明                        │
.  ├──────────────────────┼───────────────────────────────────────────────┤
.  │ OLLAMA_SERVER_URL    │ 本地 Ollama 服务地址 (默认 http://localhost:11434)│
.  │ OLLAMA_MODEL         │ 指定使用的模型名称 (如 qwen3.5:2b)            │
.  │ OLLAMA_TIMEOUT_SECONDS│ HTTP 请求超时时间，建议设置较长以适应推理延迟 │
.  │ student_id           │ 客户端实例化时传入，用于服务器端身份标识      │
.  │ USE_RAG_ENHANCEMENT  │ 全局开关，True 时启用知识库检索增强 Prompt    │
.  └──────────────────────┴───────────────────────────────────────────────┘

作者: Sacire
"""
import os
import time
import httpx
from HBPU_Student_Client.client import ArenaClient

# 导入 RAG 模块
try:
    from HBPU_Student_Client.Models.RAG import custom_rag_function
except ImportError:
    try:
        from Models.RAG import custom_rag_function
    except ImportError:
        def custom_rag_function(query): return "RAG模块加载失败"

# 全局变量控制是否开启 RAG
USE_RAG_ENHANCEMENT = False

# -------- vllm 版本 ---------#
# VLLM_SERVER_URL = "http://172.16.118.205:38080/v1/chat/completions"
# VLLM_MODEL = "qwen2-1.5"
# VLLM_TIMEOUT_SECONDS = 60.0
# VLLM_API_KEY = os.getenv("VLLM_API_KEY", "sk-ResGeDasFastAsLightning2026")

# -------- ollama 配置 ---------#
OLLAMA_SERVER_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3.5:2b"  # 模型名称
OLLAMA_TIMEOUT_SECONDS = 120.0  # 增加到120秒

# -------- vllm 提示词 ---------#
# def build_local_prompt(task) -> str:
#     return (
#         f"任务要求：请根据以下内容生成一个直接的回答，回答要贴近任务主题。\n"
#         f"任务类型：{task.task_type}\n"
#         f"任务内容：{task.content}\n\n"
#         "请给出简洁明了的答案。"
#     )
    
def build_local_prompt(task) -> str:
    """
    构建发送给本地模型的提示词 (Prompt)
    
    职责：
    根据传入的任务对象，格式化生成符合模型要求的输入文本。
    
    参数:
        task: Task 对象，包含 task_type, content 等属性
    
    返回:
        str: 格式化后的提示词字符串
    """
    prompt = (
        f"任务要求：请根据以下内容生成一个直接的回答，回答要贴近任务主题。\n"
        f"任务类型：{task.task_type} \n"
        f"任务内容：{task.content} \n"
    )

    # 如果启用了 RAG 增强
    if USE_RAG_ENHANCEMENT:
        print(f"🔍 正在检索知识库以增强回答...")
        rag_context = custom_rag_function(task.content)
        prompt += f"\n参考知识库信息：\n{rag_context}\n"
        prompt += "\n请结合上述参考信息回答任务内容。"
    
    return prompt

# -------- vllm 版本 ---------#
# def generate_local_answer(task) -> str:
#     prompt = build_local_prompt(task)
#     payload = {
#         "model": VLLM_MODEL,
#         "messages": [
#             {"role": "user", "content": prompt}
#         ],
#         "temperature": 0.2,
#         "max_tokens": 512,
#     }

#     if not VLLM_API_KEY:
#         return "本地 vllm 服务调用失败：未配置 VLLM_API_KEY 环境变量。"

#     headers = {
#         "Authorization": f"Bearer {VLLM_API_KEY}",
#         "Content-Type": "application/json",
#     }

#     try:
#         with httpx.Client(timeout=VLLM_TIMEOUT_SECONDS) as client:
#             response = client.post(VLLM_SERVER_URL, json=payload, headers=headers)
#             if response.status_code != 200:
#                 return (
#                     f"本地 vllm 服务调用失败：{response.status_code} {response.reason_phrase} - "
#                     f"{response.text.strip()}"
#                 )
#             data = response.json()

#         return data["choices"][0]["message"]["content"].strip()
#     except Exception as exc:
#         return f"本地 vllm 服务调用失败：{exc}"

# -------- ollama 版本使用函数 ---------#
def extract_answer_from_thinking(thinking_text: str) -> str:
    """
    从模型的 'thinking' (思考过程) 字段中提取最终答案
    
    当模型未直接返回标准答案格式时，尝试通过关键词匹配提取结果。
    策略优先级：
    1. 查找 "Answer:" 标记后的内容
    2. 查找 "Final Answer:" 标记后的内容
    3. 查找包含计算结果关键词（如 "等于", "结果是"）的语句
    4. 直接返回原始 thinking 文本
    
    参数:
        thinking_text: 模型生成的思考过程文本
        
    返回:
        str: 提取出的答案文本
    """
    # 方法1: 查找最后的 Answer 部分
    if "Answer:" in thinking_text:
        parts = thinking_text.split("Answer:")
        if len(parts) > 1:
            return parts[-1].strip()
    
    # 方法2: 查找 Final Answer 部分
    if "Final Answer:" in thinking_text:
        parts = thinking_text.split("Final Answer:")
        if len(parts) > 1:
            return parts[-1].strip()
    
    # 方法3: 如果 thinking 中包含明确的计算结果，直接返回 thinking
    if any(keyword in thinking_text.lower() for keyword in ["等于", "结果是", "答案是", "answer", "result"]):
        return thinking_text.strip()
    
    # 方法4: 直接返回 thinking 内容（作为最后手段）
    return thinking_text.strip()


def generate_local_answer(task) -> str:
    """
    调用本地 Ollama 模型生成答案
    
    流程：
    1. 构建 Prompt
    2. 构造 API 请求 Payload
    3. 发送 POST 请求并处理响应
    4. 保存完整响应日志到 answer.txt (用于调试)
    5. 解析并返回最终答案文本
    
    参数:
        task: Task 对象
        
    返回:
        str: 模型生成的答案文本，若出错则返回错误信息字符串
    """
    prompt = build_local_prompt(task)
    
    # Ollama API 请求格式 (非 OpenAI 兼容格式)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,    # 关闭流式输出，一次性获取结果
        "think": False,     # 关闭深度思考模式（根据模型支持情况调整）
        "options": {    
            "temperature": 0.2,     # 低温度值以获得更确定的答案
            "num_predict": 2048,    # 最大预测 token 数        
        }
    }

    try:
        print(f"🔍 调用 Ollama API...")
        print(f"📝 提示词预览: {repr(prompt[:80])}")
        
        # 使用 httpx.Timeout 对象以避免警告
        with httpx.Client(timeout=httpx.Timeout(OLLAMA_TIMEOUT_SECONDS)) as client:
            response = client.post(OLLAMA_SERVER_URL, json=payload)
            
            print(f"📡 HTTP 状态码: {response.status_code}")
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"❌ API 错误: {error_msg}")
                return error_msg
            
            data = response.json()
            
            # === 调试功能：保存完整响应到 answer.txt ===
            try:
                with open("answer.txt", "w", encoding="utf-8") as f:
                    f.write("=== 完整的 Ollama API 响应 ===\n")
                    f.write(f"任务内容: {task.content}\n")
                    f.write(f"提示词: {prompt}\n")
                    f.write("=" * 50 + "\n")
                    f.write("完整的 JSON 响应:\n")
                    import json
                    f.write(json.dumps(data, ensure_ascii=False, indent=2))
                    f.write("\n" + "=" * 50 + "\n")
                    f.write("response 字段内容:\n")
                    f.write(repr(data.get("response", "")) + "\n")
                    f.write("=" * 50 + "\n")
                    f.write("thinking 字段内容:\n")
                    f.write(repr(data.get("thinking", "")) + "\n")
                print("📄 已将完整响应保存到 answer.txt 文件")
            except Exception as save_error:
                print(f"⚠️ 保存 answer.txt 时出错: {save_error}")
            # ======================================
            
            # 优先使用 response 字段，如果为空则尝试 thinking 字段
            result = data.get("response", "").strip()
            if not result:
                thinking = data.get("thinking", "").strip()
                if thinking:
                    print("💡 检测到 thinking 字段有内容，尝试从中提取答案")
                    result = extract_answer_from_thinking(thinking)
                else:
                    print("⚠️ 警告: response 和 thinking 字段都为空")
            
            print(f"✅ 收到响应，长度: {len(result)}")
            if result:
                print(f"💬 响应预览: {repr(result[:100])}")
            else:
                print("⚠️ 警告: 最终响应为空字符串")
            
            return result
            
    except Exception as exc:
        error_msg = f"异常: {type(exc).__name__}: {exc}"
        print(f"❌ {error_msg}")
        return error_msg


def run_test_client(student_id: str = "TEST_001"):
    """
    启动测试客户端
    
    职责：
    1. 初始化 ArenaClient 实例
    2. 注册任务处理器 (@on_task)
    3. 启动客户端主循环
    
    参数:
        student_id: 学生ID，用于连接服务器时的身份标识
    """
    # 增加交互提示
    global USE_RAG_ENHANCEMENT
    choice = input("\n💡 是否启用 RAG 增强检索？(y/n): ").strip().lower()
    if choice == 'y':
        USE_RAG_ENHANCEMENT = True
        print("✅ 已启用 RAG 增强模式")
    else:
        USE_RAG_ENHANCEMENT = False
        print("ℹ️ 未启用 RAG 增强，将使用原始 Prompt")

    # 实例化客户端，开启调试日志
    test_app = ArenaClient(student_id=student_id, show_debug=True)

    @test_app.on_task
    def test_handler(task):
        """
        任务处理回调函数
        当服务器下发任务时，此函数会被自动调用
        """
        print(f"\n{'=' * 50}")
        print(f"🎯 任务ID: {task.task_id}")
        print(f"📊 任务类型: {task.task_type}")
        print(f"📝 任务内容: {task.content[:80]}...")
        print(f"⏱️  超时时间: {task.timeout_sec}秒")
        print(f"{'=' * 50}\n")
        # 调用本地模型生成答案
        answer_text = generate_local_answer(task)
        print(f"🧠 本地模型回答长度: {len(answer_text)} 字符")
        print(f"🧠 本地模型回答预览: {repr(answer_text[:200])}")

        # 返回符合协议的结果字典
        # reasoning: 思考过程 (此处固定为关闭思考)
        # final_answer: 最终答案
        # tool_used: 标记使用的工具，便于后端统计
        return {
            "reasoning": f"该模型已关闭思考功能",
            "final_answer": answer_text,
            "tool_used": "local-ollama",
        }

    print("🚀 启动测试客户端（按Ctrl+C退出）...")
    # 阻塞运行，直到接收到退出信号
    test_app.run()
