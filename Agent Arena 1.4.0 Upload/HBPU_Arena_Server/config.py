"""
HBPU Agent Arena Server - 配置管理模块

本模块定义了应用的全局配置项，使用 Pydantic Settings 管理环境变量与默认值。
.  提供数据库、服务器、LLM 模型等核心组件的配置参数。
.  支持从环境变量覆盖默认值，便于多环境（开发/测试/生产）部署。
.  所有配置项均带有清晰的中文注释说明用途与修改建议。

作者: Sacire
"""
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ==================== 数据库配置 ====================
    DATABASE_URL: str = "sqlite:///arena.db"    # 数据库连接地址，默认使用 SQLite 本地文件
    
    # ==================== 服务器配置 ====================
    SERVER_HOST: str = "0.0.0.0"    # 服务器监听地址，0.0.0.0 表示接受所有网络接口的连接
    SERVER_PORT: int = 8000    # 服务器监听端口号
    
    # ==================== LLM 评分器配置 ====================
    LLM_BASE_URL: str = "https://api.deepseek.com"  # LLM API 基础地址，用于调用大模型评分
    LLM_PROVIDER: str = "openai"    # LLM 提供商类型，使用 OpenAI 兼容接口
    LLM_MODEL: str = "deepseek-chat"    # 使用的模型名称
    LLM_API_KEY: str = "your api-key"    # API 密钥，用于身份验证
    
settings = Settings()  # 实例化全局配置对象，供其他模块导入使用（如 from config import settings）