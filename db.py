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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 确保旧表也有 code 列（若不存在则添加）
        cursor.execute("ALTER TABLE bets ADD COLUMN IF NOT EXISTS code VARCHAR(9);")
        # 为 code 字段创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bets_code ON bets(code);")


conn.commit()

def get_bet_history(user_id, start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT date, code, content, amount
        FROM bets
        WHERE user_id = ? AND date BETWEEN ? AND ?
        ORDER BY date DESC, id DESC
    """, (user_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "date": row[0],
            "code": row[1],
            "content": row[2],
            "amount": row[3]
        }
        for row in rows
    ]

def get_commission_summary(user_id):
    conn = get_connection()
    c = conn.cursor()

    if USE_PG:
        # PostgreSQL 版本
        c.execute("""
            SELECT TO_CHAR(date, 'DD/MM') AS day,
                   SUM(amount),
                   SUM(commission)
            FROM bets
            WHERE user_id = %s AND date >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY day
            ORDER BY day
        """, (user_id,))
    else:
        # SQLite 版本
        c.execute("""
            SELECT strftime('%d/%m', date) AS day,
                   SUM(amount),
                   SUM(commission)
            FROM bets
            WHERE user_id = ? AND date >= date('now', '-6 days')
            GROUP BY day
            ORDER BY day
        """, (user_id,))

    rows = c.fetchall()
    conn.close()

    return rows

def delete_bet_and_commission(code: str) -> bool:
    try:
        c = conn.cursor()
        # 检查是否存在该下注
        c.execute("SELECT COUNT(*) FROM bets WHERE code = %s" if USE_PG else "SELECT COUNT(*) FROM bets WHERE code = ?", (code,))
        exists = c.fetchone()[0]
        if not exists:
            return False

        # 执行删除
        c.execute("DELETE FROM bets WHERE code = %s" if USE_PG else "DELETE FROM bets WHERE code = ?", (code,))
        conn.commit()
        return True
    except Exception as e:
        print(f"删除下注出错: {e}")
        return False

def get_recent_bet_codes(user_id, limit=5):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT code FROM bets
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# 导出连接和游标
__all__ = [
    "conn",
    "cursor",
    "delete_bet_and_commission",
    "get_commission_summary",
    "get_bet_history",
    "get_recent_bet_codes"
]
