"""
HBPU Agent Arena Server - 数据库会话管理模块

本模块负责 SQLAlchemy 数据库引擎的初始化和会话管理。
提供数据库连接池配置、会话工厂创建以及 FastAPI 依赖注入支持。

核心功能：
- 数据库引擎初始化：创建 SQLAlchemy 引擎实例
- 会话工厂：提供线程安全的数据库会话创建
- 自动建表：应用启动时自动创建所有表结构
- 依赖注入：为 FastAPI 路由提供数据库会话依赖

关键流程说明：
.  应用启动（main.py 生命周期）──→ 导入 session 模块
.          │
.          ├──→ 1. 读取 DATABASE_URL 配置
.          │       └──→ 默认: sqlite:///arena.db
.          │
.          ├──→ 2. 创建数据库引擎（create_engine）
.          │       │
.          │       ├──→ 配置连接参数（如 SQLite 的 check_same_thread=False）
.          │       │
.          │       └──→ 建立连接池（生产环境自动启用）
.          │
.          ├──→ 3. 创建会话工厂（sessionmaker）
.          │       │
.          │       ├──→ autocommit=False: 手动提交事务
.          │       ├──→ autoflush=False: 手动刷新变更
.          │       └──→ bind=engine: 绑定数据库引擎
.          │
.          └──→ 4. 自动创建表结构
.                  │
.                  └──→ Base.metadata.create_all(bind=engine)
.                          │
.                          └──→ 扫描所有继承 Base 的模型类
.                                  │
.                                  ├──→ Student 表
.                                  └──→ Score 表
.
.  FastAPI 路由处理请求 ──→ 调用 get_db() 依赖
.          │
.          ├──→ 1. 创建数据库会话（SessionLocal()）
.          │
.          ├──→ 2. yield db（将会话传递给路由函数）
.          │
.          ├──→ 3. 路由函数执行数据库操作
.          │       │
.          │       ├──→ db.query() 查询数据
.          │       ├──→ db.add() 添加记录
.          │       ├──→ db.commit() 提交事务
.          │       └──→ db.rollback() 回滚（异常时）
.          │
.          └──→ 4. finally 块执行 db.close()
.                  │
.                  └──→ 归还连接到连接池 / 关闭连接

会话生命周期示意：
.  ┌─────────────────────────────────────────────────────────────┐
.  │                    请求进入 FastAPI 路由                      │
.  └─────────────────────────────────────────────────────────────┘
.                              │
.                              ▼
.  ┌─────────────────────────────────────────────────────────────┐
.  │  Depends(get_db) → SessionLocal() → 创建新会话                │
.  └─────────────────────────────────────────────────────────────┘
.                              │
.                              ▼
.  ┌─────────────────────────────────────────────────────────────┐
.  │            yield db（路由函数获得数据库会话）                  │
.  └─────────────────────────────────────────────────────────────┘
.                              │
.                              ▼
.  ┌─────────────────────────────────────────────────────────────┐
.  │              路由函数执行数据库 CRUD 操作                      │
.  └─────────────────────────────────────────────────────────────┘
.                              │
.                              ▼
.  ┌─────────────────────────────────────────────────────────────┐
.  │          finally: db.close() → 会话关闭，连接归还              │
.  └─────────────────────────────────────────────────────────────┘

数据库连接配置说明：
.  ┌─────────────────────┬────────────────────────────────────────┐
.  │      配置项          │                 说明                    │
.  ├─────────────────────┼────────────────────────────────────────┤
.  │ DATABASE_URL        │ 数据库连接字符串                        │
.  │                     │ - sqlite:///arena.db（SQLite 本地文件）  │
.  │                     │ - postgresql://...（PostgreSQL）        │
.  │                     │ - mysql://...（MySQL）                  │
.  ├─────────────────────┼────────────────────────────────────────┤
.  │ check_same_thread   │ SQLite 专用，允许多线程访问同一连接       │
.  │                     │ 设为 False 以支持 FastAPI 异步环境       │
.  ├─────────────────────┼────────────────────────────────────────┤
.  │ autocommit=False    │ 禁用自动提交，需要手动调用 commit()      │
.  ├─────────────────────┼────────────────────────────────────────┤
.  │ autoflush=False     │ 禁用自动刷新，手动控制变更同步时机         │
.  └─────────────────────┴────────────────────────────────────────┘

使用示例：
.  # 在路由函数中使用
.  @router.get("/students")
.  def get_students(db: Session = Depends(get_db)):
.      return db.query(Student).all()
.
.  # 在独立脚本中使用（如后台任务）
.  def save_answer(answer):
.      db = SessionLocal()
.      try:
.          db.add(answer)
.          db.commit()
.      finally:
.          db.close()

作者: Sacire
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import settings
from database.models import Base

# --- 数据库引擎初始化 ---
# 创建数据库引擎实例
# check_same_thread=False 允许在多线程环境中使用 SQLite
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- 自动创建表结构 ---
# 根据所有继承自 Base 的模型类，自动创建对应的数据库表
Base.metadata.create_all(bind=engine)

# --- FastAPI 依赖函数 ---
def get_db():
    """FastAPI 依赖项，用于获取数据库会话
    
    在 FastAPI 路由中使用 Depends(get_db) 注入数据库会话。
    使用 yield 实现上下文管理，确保会话正确关闭。
    
    Yields:
        Session: SQLAlchemy 数据库会话对象
    
    Example:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()