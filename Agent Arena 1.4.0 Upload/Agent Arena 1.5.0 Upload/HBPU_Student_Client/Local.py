"""
local.py - 本地 FastAPI 测试服务器模块

提供一个简单的 Web 界面，用于测试本地 Ollama 模型。
功能包括：
- 通过网页输入 Prompt 和系统指令
- 选择不同的本地模型
- 配置 RAG 增强（如果可用）
- 查看详细的 API 响应
"""
import os
import sys
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx
import json

# --- 配置区 ---
# 尝试导入 RAG 功能，如果不存在则使用存根函数
try:
    from HBPU_Student_Client.Models.RAG import custom_rag_function
except ImportError:
    try:
        from Models.RAG import custom_rag_function
    except ImportError:
        def custom_rag_function(query):
            return "RAG模块未找到或已禁用。"

# 默认的 Ollama 配置
OLLAMA_API_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen3.5:2b"
TIMEOUT_SECONDS = 300  # 增加超时时间到 5 分钟

# --- FastAPI 应用 ---
app = FastAPI(title="HBPU 本地模型测试器", description="用于调试本地 Ollama 模型")
templates = Jinja2Templates(directory="templates") # 模板目录

# 确保模板目录存在
if not Path("templates").exists():
    Path("templates").mkdir()

# --- HTML 界面 ---
# 这里使用内联 HTML 以简化部署，实际项目中建议使用独立的 HTML 文件
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>HBPU 本地模型测试</title>
    <style>
        body { font-family: "Microsoft YaHei", sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #333; text-align: center; }
        label { display: block; margin-top: 15px; font-weight: bold; color: #555; }
        input[type="text"], select { width: 100%; padding: 10px; margin-top: 5px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        textarea { width: 100%; height: 150px; padding: 10px; margin-top: 5px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; resize: vertical; }
        button { background: #0078d7; color: white; padding: 12px 30px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-top: 20px; }
        button:hover { background: #005a9e; }
        .result { margin-top: 20px; padding: 15px; background: #f0f0f0; border-left: 4px solid #0078d7; white-space: pre-wrap; }
        .status { color: #d70078; font-size: 14px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎓 HBPU 本地模型调试助手</h1>
        <form action="/test" method="post">
            <label for="model">选择模型:</label>
            <select name="model" id="model">
                <option value="qwen3.5:2b">Qwen3.5:2b (默认)</option>
                <option value="llama3">Llama3</option>
                <!-- 可以根据本地情况添加更多选项 -->
            </select>

            <label for="system_prompt">系统 Prompt (System):</label>
            <textarea name="system_prompt" id="system_prompt" placeholder="你是一个乐于助人的AI助手..."></textarea>

            <label for="user_input">用户输入 (User):</label>
            <textarea name="user_input" id="user_input" placeholder="请写一首关于春天的诗"></textarea>

            <label>
                <input type="checkbox" name="use_rag" value="true"> 启用 RAG 知识库增强
            </label>

            <button type="submit">🚀 发送并生成答案</button>
        </form>

        {% if result %}
        <div class="result">
            <h3>API 原始响应:</h3>
            <pre>{{ result }}</pre>
        </div>
        {% endif %}

        <div class="status" id="status"></div>
    </div>
</body>
</html>
"""

# 将内联 HTML 写入模板文件（临时方案）
with open("templates/index.html", "w", encoding="utf-8") as f:
    f.write(INDEX_HTML)

@app.get("/", response_class=HTMLResponse)
async def get_form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/test", response_class=HTMLResponse)
async def test_model(
    request: Request,
    model: str = Form(DEFAULT_MODEL),
    system_prompt: str = Form(""),
    user_input: str = Form(""),
    use_rag: str = Form(None)
):
    # 1. 处理 RAG
    rag_context = ""
    if use_rag:
        print("🔍 正在通过 RAG 检索知识库...")
        rag_context = custom_rag_function(user_input)
    
    # 2. 构建最终 Prompt
    final_prompt = ""
    if system_prompt:
        final_prompt += f"System: {system_prompt}\n\n"
    
    if rag_context:
        final_prompt += f"Reference Info:\n{rag_context}\n\n"
    
    final_prompt += f"User: {user_input}\nAssistant:"

    # 3. 调用 Ollama
    payload = {
        "model": model,
        "prompt": final_prompt,
        "stream": False,    # 关闭流式输出，一次性获取结果
        "think": False,     # 关闭深度思考模式（根据模型支持情况调整）
        "options": {    
            "temperature": 0.2,     # 低温度值以获得更确定的答案
            "num_predict": 2048,    # 最大预测 token 数        
        }
    }

    print(f"📤 正在调用 Ollama API: {OLLAMA_API_URL}")
    print(f"📝 Payload: model={model}, prompt_length={len(final_prompt)}")
    
    status = ""
    try:
        # 使用精细的超时配置
        timeout_config = httpx.Timeout(
            connect=10.0,      # 连接超时 10 秒
            read=TIMEOUT_SECONDS,  # 读取超时 5 分钟
            write=10.0,        # 写入超时 10 秒
            pool=10.0          # 连接池超时 10 秒
        )
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            response = await client.post(OLLAMA_API_URL, json=payload)
            print(f"📥 收到响应: status_code={response.status_code}")
            if response.status_code == 200:
                data = response.json()
                # 提取实际响应文本，而不是显示整个 JSON
                actual_response = data.get("response", "")
                thinking = data.get("thinking", "")
                
                # 构建更友好的显示结果
                result_parts = []
                result_parts.append(f"✅ 模型响应:\n{actual_response}")
                if thinking:
                    result_parts.append(f"\n\n💭 思考过程 (已截断):\n{thinking[:500]}...")
                result_parts.append("\n\n\n\n=== 完整的 Ollama API 响应 ===")
                result_parts.append(f"任务内容: {user_input}")  # 注意：Local.py 中是 user_input，不是 task.content
                result_parts.append(f"提示词: {final_prompt}")
                result_parts.append(f"\n\n📊 统计信息:")
                result_parts.append(f"  - 总耗时: {data.get('total_duration', 0) / 1e9:.2f} 秒")
                result_parts.append(f"  - 生成 tokens: {data.get('eval_count', 0)}")
                
                result = "\n".join(result_parts)
                status = "✅ 请求成功！"
            else:
                result = f"❌ 错误 {response.status_code}:\n{response.text}"
                status = "❌ 请求失败。"
    except Exception as e:
        result = f"❌ 异常: {str(e)}"
        status = "❌ 连接异常，请检查 Ollama 是否运行。"

    # 返回渲染后的页面，带上结果
    return templates.TemplateResponse(
        "index.html", 
        {   
            "request": request, 
            "result": result, 
            "status": status,
            "model": model,
            "system_prompt": system_prompt,
            "user_input": user_input
        }
    )

def start_local_server():
    """
    启动本地 FastAPI 测试服务器的入口函数。
    """
    import uvicorn
    print("💡 本地测试服务启动中...")
    print("👉 请在浏览器中访问 http://127.0.0.1:8000")
    print("⌨️  按 Ctrl+C 停止服务")
    
    # 使用 uvicorn 运行应用
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

# 如果直接运行 local.py，也启动服务
if __name__ == "__main__":
    start_local_server()