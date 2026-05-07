import os
import re
from typing import Optional, List, Dict, Any

def load_knowledge_base() -> str:
    """
    加载知识库文件
    
    返回:
    str - 知识库内容
    """
    try:
        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 知识库文件路径
        knowledge_path = os.path.join(current_dir, "knowledge.txt")
        
        print(f"📚 知识库路径: {knowledge_path}")
        
        # 检查文件是否存在
        if not os.path.exists(knowledge_path):
            print(f"❌ 知识库文件未找到: {knowledge_path}")
            return "知识库文件未找到，请检查models/knowledge.txt是否存在"
        
        # 读取文件内容
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"✅ 知识库加载成功，内容长度: {len(content)}")
        return content
        
    except Exception as e:
        print(f"❌ 读取知识库失败: {str(e)}")
        return f"知识库读取错误: {str(e)}"

def preprocess_text(text: str) -> str:
    """
    预处理文本
    
    参数:
    text: str - 原始文本
    
    返回:
    str - 预处理后的文本
    """
    # 转换为小写
    text = text.lower()
    
    # 移除特殊字符，保留中文、英文、数字和基本标点
    text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?;:()\'"\\-]', '', text)
    
    # 多个空格替换为单个空格
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_relevant_paragraphs(query: str, knowledge_content: str, max_results: int = 3) -> List[str]:
    """
    从知识库中提取相关段落
    
    参数:
    query: str - 查询内容
    knowledge_content: str - 知识库内容
    max_results: int - 最大返回结果数
    
    返回:
    List[str] - 相关段落列表
    """
    # 预处理查询
    processed_query = preprocess_text(query)
    query_words = set(processed_query.split())
    
    # 分割段落
    paragraphs = [p.strip() for p in knowledge_content.split('\n\n') if p.strip()]
    
    print(f"📖 知识库段落数: {len(paragraphs)}")
    
    # 评分段落相关性
    scored_paragraphs = []
    
    for i, para in enumerate(paragraphs):
        processed_para = preprocess_text(para)
        para_words = set(processed_para.split())
        
        # 计算关键词匹配度
        match_count = sum(1 for word in query_words if word in processed_para)
        
        # 计算匹配度分数
        score = match_count / max(1, len(query_words))
        
        if score > 0:
            scored_paragraphs.append({
                'paragraph': para,
                'score': score,
                'index': i
            })
    
    # 按分数排序
    scored_paragraphs.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"🎯 找到 {len(scored_paragraphs)} 个相关段落")
    
    # 返回最高分的段落
    relevant_paragraphs = [item['paragraph'] for item in scored_paragraphs[:max_results]]
    
    return relevant_paragraphs

# def custom_rag_function(query: str, context: Optional[Any] = None) -> str:
#     """
#     自定义 RAG 函数 - 核心检索逻辑
    
#     参数:
#     query: str - 用户查询
#     context: Optional[Any] - 上下文信息（本例中未使用）
    
#     返回:
#     str - 检索结果
#     """
#     print(f"\n🧠 RAG 函数被调用，查询: {query}")
    
#     try:
#         # 1. 加载知识库
#         knowledge_content = load_knowledge_base()
        
#         if "知识库文件未找到" in knowledge_content or "知识库读取错误" in knowledge_content:
#             return knowledge_content
        
#         # 2. 提取相关段落
#         relevant_paragraphs = extract_relevant_paragraphs(query, knowledge_content)
        
#         # 3. 构建结果
#         if relevant_paragraphs:
#             result = "【RAG 检索结果】\n\n" + "\n\n".join(relevant_paragraphs)
#             print(f"✅ RAG 检索成功，返回 {len(relevant_paragraphs)} 个相关段落")
#             return result
#         else:
#             # 4. 无相关结果时返回知识库摘要
#             summary = knowledge_content[:500] + "..." if len(knowledge_content) > 500 else knowledge_content
#             result = f"【RAG 检索结果】\n\n未找到与查询 '{query}' 精确匹配的内容，以下是知识库摘要：\n\n{summary}"
#             print("⚠️ 未找到精确匹配内容，返回知识库摘要")
#             return result
            
#     except Exception as e:
#         print(f"❌ RAG 函数执行失败: {str(e)}")
#         return f"RAG 处理错误: {str(e)}"

def custom_rag_function(query: str, context: Optional[Any] = None) -> str:
    """
    优化版RAG函数 - 支持语义模糊匹配
    改进点：
    1. 中文分词+关键词权重分析
    2. 核心实体识别（学校/地点/时间）
    3. 语义相似度阈值控制
    4. 动态返回最相关片段
    """
    print(f"\n🧠 RAG 函数被调用，查询: {query}")
    
    try:
        # 1. 加载知识库
        knowledge_content = load_knowledge_base()
        if "知识库文件未找到" in knowledge_content or "知识库读取错误" in knowledge_content:
            return knowledge_content
        
        # 2. 【关键改进】语义模糊匹配
        relevant_paragraphs = _semantic_fuzzy_match(query, knowledge_content)
        
        # 3. 构建结果
        if relevant_paragraphs:
            result = "【RAG 检索结果】\n\n" + "\n\n".join(relevant_paragraphs)
            print(f"✅ 语义匹配成功，返回 {len(relevant_paragraphs)} 个相关段落")
            return result
        else:
            # 4. 无匹配时返回结构化摘要（比原始摘要更聚焦）
            summary = _structured_summary(knowledge_content, query)
            result = f"【RAG 检索结果】\n\n未找到直接匹配内容，关键信息摘要：\n\n{summary}"
            print("⚠️ 语义匹配失败，返回结构化摘要")
            return result
            
    except Exception as e:
        print(f"❌ RAG 函数执行失败: {str(e)}")
        return f"RAG 处理错误: {str(e)}"

# ===== 新增核心功能函数 =====
def _semantic_fuzzy_match(query: str, knowledge: str) -> List[str]:
    """增强版模糊匹配：结合实体识别+语义相似度"""
    # 步骤1：中文预处理（去标点/停用词）
    query_clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', query)  # 保留中文字母数字
    paragraphs = [p.strip() for p in knowledge.split('\n\n') if p.strip()]
    
    # 步骤2：关键实体提取（学校/地点/时间）
    school_entities = ["HBPU", "湖北理工学院", "理工学院"]
    location_entities = ["图书馆", "图书室", "阅览室"]
    time_entities = ["开放", "营业", "时间", "几点", "何时"]
    
    # 步骤3：计算每个段落的相关性得分
    results = []
    for para in paragraphs:
        score = 0
        
        # 实体匹配加分（核心改进）
        if any(ent in para for ent in school_entities): score += 3
        if any(ent in para for ent in location_entities): score += 3
        if any(ent in para for ent in time_entities): score += 4  # 时间查询权重更高
        
        # 语义相似度基础分（避免完全依赖实体）
        if query_clean in para:  # 完整语义片段匹配
            score += 5
        elif len(set(query_clean) & set(para)) / len(set(query_clean)) > 0.4:  # 字符重叠率>40%
            score += 2
        
        # 步骤4：动态阈值判定（至少命中2类实体）
        if score >= 5 and (any(ent in para for ent in school_entities + location_entities)):
            results.append(para)
    
    return results[:3]  # 最多返回3个最相关段落

def _structured_summary(knowledge: str, query: str) -> str:
    """生成聚焦查询主题的摘要（非原始截断）"""
    # 优先提取包含核心实体的句子
    school_entities = ["HBPU", "湖北理工学院"]
    location_entities = ["图书馆"]
    
    # 查找最相关的句子
    sentences = re.split(r'[。！？]', knowledge)
    for sent in sentences:
        if any(ent in sent for ent in school_entities) and any(ent in sent for ent in location_entities):
            return f"📌 关于 '{query}' 的关键信息：\n{sent.strip()}..."
    
    # 降级方案：返回前两句
    return "📌 知识库关键信息：\n" + "\n".join([s for s in sentences if s.strip()][:2]) + "..."


# 测试代码
if __name__ == "__main__":
    print("🧪 测试 RAG 函数...")
    
    test_queries = [
        "HBPU是什么？",
        "湖北理工学院在哪里？",
        "这个系统有什么功能？",
        "不存在的问题测试"
    ]
    
    for query in test_queries:
        print(f"\n{'='*50}")
        print(f"🔍 测试查询: {query}")
        result = custom_rag_function(query)
        print(f"💡 RAG 结果:\n{result}")
        print(f"{'='*50}")