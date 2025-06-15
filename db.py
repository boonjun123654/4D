import os
import psycopg2
import sqlite3
import logging
import pytz

logger = logging.getLogger(__name__)

USE_PG = bool(os.getenv("DATABASE_URL"))

# ✅ 统一获取连接函数
def get_conn():
    if USE_PG:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.autocommit = True
        return conn
    else:
        return sqlite3.connect("data.db", check_same_thread=False)

# ✅ 初始化表结构（只需执行一次）
def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    if USE_PG:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id SERIAL PRIMARY KEY,
            agent_id BIGINT NOT NULL,
            bet_date DATE NOT NULL,
            market TEXT NOT NULL,
            number VARCHAR(20) NOT NULL,
            bet_type VARCHAR(4) NOT NULL,
            mode VARCHAR(4),
            amount NUMERIC NOT NULL,
            potential_win NUMERIC NOT NULL,
            commission NUMERIC NOT NULL,
            code VARCHAR(9) NOT NULL,
            group_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
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
            group_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()

def get_bet_history(start_date, end_date, group_id):
    conn = get_conn()
    c = conn.cursor()
    if USE_PG:
        c.execute("""
            SELECT bet_date, code, number, bet_type, amount, market
            FROM bets
            WHERE group_id = %s AND bet_date BETWEEN %s AND %s
            ORDER BY bet_date DESC
        """, (group_id, start_date, end_date))

    else:
        c.execute("""
            SELECT bet_date, code, number, bet_type, amount, market
            FROM bets
            WHERE group_id = ? AND bet_date BETWEEN ? AND ?
            ORDER BY bet_date DESC
        """, (user_id, group_id, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
    rows = c.fetchall()
    data = [
        {
            "date": r[0],
            "code": r[1],
            "number": r[2],
            "bet_type": r[3],
            "amount": r[4],
            "market": r[5]
        }
        for r in rows
    ]

    conn.close()
    return data

def get_commission_summary(start_date, end_date, group_id):
    """
    生成最近 7 天的佣金报表，其中 “总额” = 每条下注的 amount × market 个数
    返回格式：
    [
      {"day": "10/06", "total_amount": 15.0, "total_commission": 3.9},
      {"day": "11/06", "total_amount": 15.0, "total_commission": 3.9},
      ...
    ]
    """
    conn = get_conn()
    c = conn.cursor()

    if USE_PG:
        # Postgres: 用 string_to_array + cardinality 计算 market 数
        c.execute("""
            SELECT
              TO_CHAR(bet_date, 'DD/MM') AS day,
              SUM(amount * CARDINALITY(string_to_array(market, ',')))      AS total_amount,
              SUM(commission)                                              AS total_commission
            FROM bets
            WHERE group_id  = %s
              AND bet_date BETWEEN %s AND %s
            GROUP BY day
            ORDER BY day DESC
        """, (group_id, start_date, end_date))

    else:
        # SQLite: 用 string 函数计算逗号数再 +1
        c.execute("""
            SELECT
              strftime('%d/%m', bet_date) AS day,
              SUM(
                amount
                * (
                    LENGTH(market)
                    - LENGTH(REPLACE(market, ',', ''))
                    + 1
                  )
              )                               AS total_amount,
              SUM(commission)                  AS total_commission
            FROM bets
            WHERE group_id  = ?
              AND bet_date BETWEEN ? AND ?
            GROUP BY day
            ORDER BY day DESC
        """, (
            group_id,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d'),
        ))

    rows = c.fetchall()
    conn.close()

    return [
        {
            "day":              r[0],
            "total_amount":     float(r[1]),
            "total_commission": float(r[2]),
        }
        for r in rows
    ]

def get_recent_bet_codes(group_id=None):
    conn = get_conn()
    c = conn.cursor()
    try:
        tz = pytz.timezone("Asia/Kuala_Lumpur")
        now = datetime.now(tz)
        today = now.date()

        # 当前时间的锁注点（当天19:00）
        lock_datetime_today = datetime.combine(today, time(19, 0)).astimezone(tz)

        # 查询所有 code + bet_date
        if group_id:
            query = """
                SELECT DISTINCT code, bet_date
                FROM bets
                WHERE group_id = %s
                ORDER BY code DESC, created_at DESC
            """
            c.execute(query, (group_id,))
        else:
            query = """
                SELECT DISTINCT code, bet_date
                FROM bets
                ORDER BY code DESC, created_at DESC
            """
            c.execute(query)

        rows = c.fetchall()
        conn.close()

        # 过滤出未锁注的 code
        valid_codes = []
        for code, bet_datetime in rows:
            if isinstance(bet_datetime, str):
                bet_datetime = datetime.fromisoformat(bet_datetime)
            bet_date = bet_datetime.date()
            lock_datetime = datetime.combine(bet_date, time(19, 0)).astimezone(tz)

            if now < lock_datetime:
                valid_codes.append(code)

        return valid_codes

    except Exception as e:
        logger.error(f"❌ 读取下注 code 出错: {e}")
        return []

def delete_bet_and_commission(code, group_id):
    conn = get_conn()
    c = conn.cursor()
    try:
        if USE_PG:
            c.execute("DELETE FROM bets WHERE code = %s AND group_id = %s", (code, group_id))
        else:
            c.execute("DELETE FROM bets WHERE code = ? AND group_id = ?", (code, group_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"删除失败：{e}")
        conn.close()
        return False

# 导出连接和游标
__all__ = ["conn", "cursor", "get_bet_history", "get_commission_summary", "get_recent_bet_codes", "delete_bet_and_commission"]
