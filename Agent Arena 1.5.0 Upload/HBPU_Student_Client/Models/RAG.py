import os
import re
import jieba
import jieba.analyse  # 用于关键词提取
from typing import Optional, List, Dict, Any

def load_knowledge_base() -> str:
    """加载知识库文件"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        knowledge_path = os.path.join(current_dir, "knowledge.txt")
        print(f"📚 知识库路径: {knowledge_path}")

        if not os.path.exists(knowledge_path):
            print(f"❌ 知识库文件未找到: {knowledge_path}")
            return "知识库文件未找到，请检查 knowledge.txt 是否存在"

        with open(knowledge_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"✅ 知识库加载成功，内容长度: {len(content)}")
        return content
    except Exception as e:
        print(f"❌ 读取知识库失败: {str(e)}")
        return f"知识库读取错误: {str(e)}"

def preprocess_text(text: str) -> str:
    """预处理文本（统一小写，去除非必要字符）"""
    text = text.lower()
    # 保留中文、英文、数字、基本标点和空格
    text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?;:()\'"-]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _extract_keywords(text: str, top_k: int = 5) -> List[str]:
    """
    使用 Jieba 提取关键词
    这是实现“高级模糊匹配”的核心：自动识别核心概念，而非硬编码
    """
    # 使用 TF-IDF 算法提取关键词
    keywords = jieba.analyse.extract_tags(text, topK=top_k, withWeight=False)
    return keywords

def _semantic_fuzzy_match(query: str, knowledge: str) -> List[str]:
    """
    增强版模糊匹配：结合【自动关键词提取】+【动态语义相似度】
    """
    # 1. 预处理
    query_clean = preprocess_text(query)
    paragraphs = [p.strip() for p in knowledge.split('\n\n') if len(p.strip()) > 5] # 过滤太短的段落
    
    # 2. 【核心改进】自动提取用户问题的关键词，不再依赖硬编码
    query_keywords = _extract_keywords(query_clean, top_k=4)
    print(f"🔍 问题 '{query}' 提取的关键词: {query_keywords}")

    # 3. 计算每个段落的相关性得分
    results_with_score = []

    for para in paragraphs:
        para_processed = preprocess_text(para)
        score = 0.0

        # --- 策略 A：关键词命中权重 (最重要) ---
        # 如果知识库段落中包含了用户问题的关键词，加分
        for keyword in query_keywords:
            if len(keyword) > 1:  # 只考虑长度大于1的词
                if keyword in para_processed:
                    # 根据关键词长度给分，长词（更具体）权重更高
                    score += 3.0 + (len(keyword) * 0.5)

        # --- 策略 B：核心实体/缩写识别 (适配你的学校场景) ---
        # 这里可以保留一点针对你特定需求的逻辑，比如识别 "HBPU" 这种缩写
        # 但写法更通用：如果问题里有大写字母缩写，且在段落中出现，给高分
        uppercase_in_query = re.findall(r'\b[A-Z]{2,}\b', query)
        for abbr in uppercase_in_query:
            if abbr in para:
                score += 5.0 # 缩写匹配给高分，因为通常代表核心主题

        # --- 策略 C：字符重叠率/语义片段 ---
        # 防止漏网之鱼，计算字符重叠率
        if len(query_clean) > 0:
            common_chars = set(query_clean) & set(para_processed)
            overlap_ratio = len(common_chars) / len(set(query_clean))
            if overlap_ratio > 0.5: # 重叠率超过50%
                score += 1.0

        # --- 策略 D：完整短语匹配 ---
        # 如果问题中的某个短语完整出现在段落中
        if query_clean in para_processed:
            score += 4.0

        # --- 结果判定 ---
        # 只有得分大于0的段落才被认为是相关的
        if score > 0:
            results_with_score.append({
                'paragraph': para,
                'score': score
            })

    # 4. 按分数排序，取 Top 3
    results_with_score.sort(key=lambda x: x['score'], reverse=True)
    print(f"📊 匹配得分分析: 共找到 {len(results_with_score)} 个候选段落")

    # 提取段落文本
    final_results = [item['paragraph'] for item in results_with_score[:3]]
    return final_results

def _structured_summary(knowledge: str, query: str) -> str:
    """生成聚焦查询主题的摘要"""
    sentences = re.split(r'[。！？]', knowledge)
    # 尝试找包含关键词的句子
    for sent in sentences:
        if len(sent) > 10: # 太短的不要
            return f"📌 关于 '{query}' 的关键信息：\n{sent.strip()}..."
    return "📌 知识库关键信息：\n" + "\n".join([s for s in sentences if s.strip()][:2]) + "..."

def custom_rag_function(query: str, context: Optional[Any] = None) -> str:
    """优化版RAG函数"""
    print(f"\n🧠 RAG 函数被调用，查询: {query}")
    
    try:
        knowledge_content = load_knowledge_base()
        if "知识库文件未找到" in knowledge_content or "知识库读取错误" in knowledge_content:
            return knowledge_content

        # 使用改进后的模糊匹配
        relevant_paragraphs = _semantic_fuzzy_match(query, knowledge_content)

        if relevant_paragraphs:
            result = "【RAG 检索结果】\n\n" + "\n\n".join(relevant_paragraphs)
            print(f"✅ 语义匹配成功，返回 {len(relevant_paragraphs)} 个相关段落")
            return result
        else:
            summary = _structured_summary(knowledge_content, query)
            result = f"【RAG 检索结果】\n\n未找到直接匹配内容，关键信息摘要：\n\n{summary}"
            print("⚠️ 语义匹配失败，返回结构化摘要")
            return result

    except Exception as e:
        print(f"❌ RAG 函数执行失败: {str(e)}")
        return f"RAG 处理错误: {str(e)}"

# 测试代码
if __name__ == "__main__":
    print("🧪 测试 RAG 函数...")
    test_queries = [
        "陈平安是谁？",
        "小镇上有哪些高人？",
        "小镇的圣人是谁？"
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"🔍 测试查询: {query}")
        result = custom_rag_function(query)
        print(f"💡 RAG 结果:\n{result}")
        print(f"{'='*60}")