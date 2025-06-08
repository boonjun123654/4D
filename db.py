import os
import sqlite3

# 读取环境变量，优先使用 PostgreSQL，否则降级到 SQLite 本地文件
database_url = os.getenv("DATABASE_URL")

if database_url:
    # 生产环境：PostgreSQL
    import psycopg2
    conn = psycopg2.connect(database_url)
else:
    # 本地调试：SQLite
    conn = sqlite3.connect("data.db", check_same_thread=False)

cursor = conn.cursor()

# 初始化 bets 表结构
if database_url:
    # PostgreSQL 模式
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id SERIAL PRIMARY KEY,
        agent_id BIGINT NOT NULL,
        bet_date DATE NOT NULL,
        market CHAR(1) NOT NULL,
        number VARCHAR(4) NOT NULL,
        bet_type VARCHAR(4) NOT NULL,
        mode VARCHAR(8),
        amount NUMERIC NOT NULL,
        potential_win NUMERIC NOT NULL,
        commission NUMERIC NOT NULL,
        code VARCHAR(9) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # 为 code 字段创建索引以加速删除与查询
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_bets_code ON bets(code);
    """)
else:
    # SQLite 模式
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id INTEGER NOT NULL,
        bet_date TEXT NOT NULL,
        market TEXT NOT NULL,
        number TEXT NOT NULL,
        bet_type TEXT NOT NULL,
        mode TEXT,
        amount REAL NOT NULL,
        potential_win REAL NOT NULL,
        commission REAL NOT NULL,
        code TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # SQLite 为 code 字段创建索引
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_bets_code ON bets(code);
    """)

conn.commit()

# 导出连接和游标
__all__ = ["conn", "cursor"]
