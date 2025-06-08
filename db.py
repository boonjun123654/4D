import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
import os

DB_URL = os.getenv("DATABASE_URL")  # Render 上设置的 DATABASE_URL

def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

# 初始化表结构（仅首次执行）
def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                date TEXT,
                market CHAR(1),
                number TEXT,
                bet_type CHAR(1),
                amount INTEGER,
                box_type TEXT,
                created_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS results (
                id SERIAL PRIMARY KEY,
                date TEXT,
                market CHAR(1),
                prize_type TEXT,   -- e.g. '1', '2', '3', 'special', 'consolation'
                number TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                is_agent BOOLEAN DEFAULT TRUE
            );
            """)
            conn.commit()


# 储存下注
def save_bets(user_id, bets):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for b in bets:
                cur.execute("""
                INSERT INTO bets (user_id, date, market, number, bet_type, amount, box_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    user_id, b["date"], b["market"], b["number"], b["bet_type"],
                    b["amount"], b["box_type"], b["created_at"]
                ))
            conn.commit()


# 保证 get_user_bets 函数定义在 db.py
# 如果未定义，添加下面这个函数

def get_user_bets(user_id):
    from psycopg2.extras import RealDictCursor
    import psycopg2
    import os
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT date, market, number, bet_type, amount, box_type FROM bets WHERE user_id = %s ORDER BY date DESC", (user_id,))
        return cur.fetchall()


# 删除下注（只能删除自己）
def delete_user_bets(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bets WHERE user_id = %s", (user_id,))
            conn.commit()

# 存储开奖号码
def save_results(results):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in results:
                cur.execute("""
                INSERT INTO results (date, market, prize_type, number)
                VALUES (%s, %s, %s, %s)
                """, (r["date"], r["market"], r["prize_type"], r["number"]))
            conn.commit()

# 查询中奖记录（按用户 / 所有人）
def get_win_records(user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = "SELECT * FROM bets"
            if user_id:
                query += f" WHERE user_id = {user_id}"
            cur.execute(query)
            return cur.fetchall()

def get_user_bets(user_id):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT date, market, number, bet_type, amount, box_type FROM bets WHERE user_id = %s ORDER BY date DESC", (user_id,))
        return cur.fetchall()

def get_all_commissions():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT username, SUM(commission) as total FROM commissions GROUP BY username ORDER BY total DESC")
        return cur.fetchall()

# 赔率表（简化版，可拆出去）
def get_payout(bet_type, market, prize_type, box_type, combo_count=24):
    # 固定赔率设定
    payout_table = {
        "MKT": {
            "B": {"1": 2750, "2": 1100, "3": 550, "special": 220, "consolation": 66},
            "S": {"1": 3850, "2": 2200, "3": 1100},
            "A": {"1": 726},  # only 1st prize last 3 digits
            "C": {"1": 242, "2": 242, "3": 242}
        },
        "HL": {
            "B": {"1": 3045, "2": 1050, "3": 525, "special": 210, "consolation": 63},
            "S": {"1": 4095, "2": 2100, "3": 1050},
            "A": {"1": 740.25},
            "C": {"1": 246.75, "2": 246.75, "3": 246.75}
        }
    }

    group = "HL" if market in ["H", "L"] else "MKT"

    # box 和 ibox 赔率调整
    if box_type == "ibox":
        # 简化处理，仅演示（实际应分 24/12/6/4 组合数）
        base = payout_table[group].get(bet_type, {}).get(prize_type, 0)
        return round(base / combo_count, 2)
    else:
        return payout_table[group].get(bet_type, {}).get(prize_type, 0)

# 判断是否中奖
def check_win(bet, result_list):
    number = bet["number"]
    bet_type = bet["bet_type"]
    tail3 = number[-3:]

    wins = []

    for r in result_list:
        res_num = r["number"]
        prize_type = r["prize_type"]

        if bet_type in ["B", "S"]:  # 全匹配（box / ibox 支持）
            if bet["box_type"] in ["ibox", "box"]:
                from itertools import permutations
                combo_count = len(set(permutations(number)))
                if "".join(res_num) in ["".join(p) for p in permutations(number)]:
                    wins.append({
                        "market": bet["market"],
                        "number": number,
                        "prize": prize_type,
                        "amount": bet["amount"],
                        "box_type": bet["box_type"],
                        "win_amt": get_payout(bet_type, bet["market"], prize_type, bet["box_type"], combo_count)
                    })
            else:
                if res_num == number:
                    wins.append({
                        "market": bet["market"],
                        "number": number,
                        "prize": prize_type,
                        "amount": bet["amount"],
                        "box_type": None,
                        "win_amt": get_payout(bet_type, bet["market"], prize_type, None)
                    })

        elif bet_type == "A":
            if res_num[-3:] == tail3 and prize_type == "1":
                wins.append({
                    "market": bet["market"],
                    "number": number,
                    "prize": "1A",
                    "amount": bet["amount"],
                    "win_amt": get_payout("A", bet["market"], "1", None)
                })

        elif bet_type == "C":
            if res_num[-3:] == tail3 and prize_type in ["1", "2", "3"]:
                wins.append({
                    "market": bet["market"],
                    "number": number,
                    "prize": f"{prize_type}C",
                    "amount": bet["amount"],
                    "win_amt": get_payout("C", bet["market"], prize_type, None)
                })

    return wins

# 计算代理佣金
def calculate_commission(bet):
    # 按下注市场判断抽水比例
    rate = 0.26 if bet["market"] in ["M", "K", "T", "S"] else 0.19
    return round(bet["amount"] * rate, 2)

def get_max_win_amount(bets):
    def get_payout(bet_type, market, prize_type, box_type, combo_count=24):
        payout_table = {
            "MKT": {
                "B": {"1": 2750, "2": 1100, "3": 550, "special": 220, "consolation": 66},
                "S": {"1": 3850, "2": 2200, "3": 1100},
                "A": {"1": 726},
                "C": {"1": 242, "2": 242, "3": 242}
            },
            "HL": {
                "B": {"1": 3045, "2": 1050, "3": 525, "special": 210, "consolation": 63},
                "S": {"1": 4095, "2": 2100, "3": 1050},
                "A": {"1": 740.25},
                "C": {"1": 246.75, "2": 246.75, "3": 246.75}
            }
        }

        group = "HL" if market in ["H", "L"] else "MKT"

        if box_type == "ibox":
            base = payout_table[group].get(bet_type, {}).get(prize_type, 0)
            return round(base / combo_count, 2)
        else:
            return payout_table[group].get(bet_type, {}).get(prize_type, 0)

    total_win = 0
    for bet in bets:
        number = bet["number"]
        bet_type = bet["bet_type"]
        amount = bet["amount"]
        market = bet["market"]
        box_type = bet.get("box_type")

        group = "HL" if market in ["H", "L"] else "MKT"

        if bet_type in ["B", "S"]:
            combo_count = len(set(itertools.permutations(number))) if box_type == "ibox" else 1
            prize_keys = ["1", "2", "3", "special", "consolation"] if bet_type == "B" else ["1", "2", "3"]
            for prize in prize_keys:
                payout = get_payout(bet_type, market, prize, box_type, combo_count)
                total_win += payout * amount

        elif bet_type == "A":
            payout = get_payout("A", market, "1", None)
            total_win += payout * amount

        elif bet_type == "C":
            for prize in ["1", "2", "3"]:
                payout = get_payout("C", market, prize, None)
                total_win += payout * amount

    return total_win

load_dotenv()

def get_bet_history(user_id):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("""
        SELECT bet_date, market, number, amount, bet_type, box_type
        FROM bets
        WHERE user_id = %s
        ORDER BY bet_date DESC
        LIMIT 20;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def delete_bets(user_id):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("DELETE FROM bets WHERE user_id = %s RETURNING *;", (user_id,))
    deleted_rows = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return deleted_rows

def get_win_history(user_id):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("""
        SELECT win_date, market, number, bet_type, win_amount
        FROM win_history
        WHERE user_id = %s
        ORDER BY win_date DESC
        LIMIT 20;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def record_commission(bet_id, user_id, market, total_amount):
    # 判断市场抽水比例
    if market in ["M", "K", "T", "S"]:
        rate = 0.26
    elif market in ["H", "L"]:
        rate = 0.19
    else:
        return

    # 获取代理和老板 ID
    agent_id = get_agent_id(user_id)
    boss_id = get_boss_id()

    commission_total = total_amount * rate
    agent_commission = commission_total * 0.3
    boss_commission = commission_total * 0.7

    # 插入记录（可拆分成两条记录分别代表代理与老板）
    cursor.execute("""
        INSERT INTO commissions (bet_id, agent_id, boss_id, commission_amount, commission_type)
        VALUES (%s, %s, %s, %s, %s)
    """, (bet_id, agent_id, boss_id, agent_commission, market))

    cursor.execute("""
        INSERT INTO commissions (bet_id, agent_id, boss_id, commission_amount, commission_type)
        VALUES (%s, %s, %s, %s, %s)
    """, (bet_id, None, boss_id, boss_commission, market))


def save_win_numbers(market, win_date, prize_dict):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    # 遍历所有奖项写入数据库
    for prize_type, numbers in prize_dict.items():
        for num in numbers:
            cur.execute("""
                INSERT INTO results (market, win_date, prize_type, number)
                VALUES (%s, %s, %s, %s)
            """, (market, win_date, prize_type, num))

    conn.commit()
    cur.close()
    conn.close()


