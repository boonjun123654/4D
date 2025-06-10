import os
import sqlite3

# 读取环境变量，优先使用 PostgreSQL，否则降级到 SQLite 本地文件
database_url = os.getenv("DATABASE_URL")

if database_url:
    # 生产环境：PostgreSQL
    import psycopg2
    conn = psycopg2.connect(database_url)
    conn.autocommit = True

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
        market TEXT NOT NULL,
        number VARCHAR(4) NOT NULL,
        bet_type VARCHAR(4) NOT NULL,
        mode VARCHAR(8),
        amount NUMERIC NOT NULL,
        potential_win NUMERIC NOT NULL,
        commission NUMERIC NOT NULL,
        code VARCHAR(9) NOT NULL,
        group_id TEXT NOT NULL,
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
            group_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 确保旧表也有 code 列（若不存在则添加）
        cursor.execute("ALTER TABLE bets ADD COLUMN IF NOT EXISTS code VARCHAR(9);")
        # 为 code 字段创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bets_code ON bets(code);")


conn.commit()

def get_bet_history(user_id, start_date, end_date, group_id):
    c = conn.cursor()
    if USE_PG:
        c.execute("""
            SELECT bet_date, code, number || '-' || bet_type AS content, amount
            FROM bets
            WHERE agent_id = %s AND group_id = %s AND bet_date BETWEEN %s AND %s
            ORDER BY bet_date DESC
        """, (user_id, group_id, start_date, end_date))
    else:
        c.execute("""
            SELECT bet_date, code, number || '-' || bet_type AS content, amount
            FROM bets
            WHERE agent_id = ? AND group_id = ? AND bet_date BETWEEN ? AND ?
            ORDER BY bet_date DESC
        """, (user_id, group_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
    rows = c.fetchall()
    return [
        {"date": r[0], "code": r[1], "content": r[2], "amount": r[3]}
        for r in rows
    ]

def get_commission_summary(user_id, start_date, end_date, group_id):
    c = conn.cursor()
    if USE_PG:
        c.execute("""
            SELECT TO_CHAR(bet_date, 'DD/MM') AS day,
                   SUM(amount), SUM(commission)
            FROM bets
            WHERE agent_id = %s AND group_id = %s AND bet_date BETWEEN %s AND %s
            GROUP BY day
            ORDER BY day
        """, (user_id, group_id, start_date, end_date))
    else:
        c.execute("""
            SELECT strftime('%d/%m', bet_date) AS day,
                   SUM(amount), SUM(commission)
            FROM bets
            WHERE agent_id = ? AND group_id = ? AND bet_date BETWEEN ? AND ?
            GROUP BY day
            ORDER BY day
        """, (user_id, group_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
    rows = c.fetchall()
    return [
        {"day": r[0], "total_amount": r[1], "total_commission": r[2]}
        for r in rows
    ]


def get_recent_bet_codes(user_id, limit=5, group_id=None):
    c = conn.cursor()
    if group_id:
        query = """
            SELECT code FROM bets
            WHERE agent_id = ? AND group_id = ?
            ORDER BY created_at DESC LIMIT ?
        """
        c.execute(query, (user_id, group_id, limit))
    else:
        query = """
            SELECT code FROM bets
            WHERE agent_id = ?
            ORDER BY created_at DESC LIMIT ?
        """
        c.execute(query, (user_id, limit))
    rows = c.fetchall()
    return [r[0] for r in rows]

# 导出连接和游标
__all__ = [
    "conn",
    "cursor",
    "delete_bet_and_commission",
    "get_commission_summary",
    "get_bet_history",
    "get_recent_bet_codes"
]
