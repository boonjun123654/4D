import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = int(os.getenv("OWNER_ID"))

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def save_bets(user_id, username, parsed_bets):
    conn = get_conn()
    cur = conn.cursor()
    for b in parsed_bets:
        cur.execute("""
            INSERT INTO bets (user_id, username, market_code, number, bet_type, is_box, is_ibox, amount, draw_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, username, b['market'], b['number'], b['type'], b['is_box'], b['is_ibox'], b['amount'], b['date']))
        
        # 佣金计算
        rate = 0.26 if b['market'] in ['M','K','T','S'] else 0.19
        commission = round(b['amount'] * rate, 2)
        owner_earn = round(b['amount'] - commission, 2)
        cur.execute("""
            INSERT INTO commissions (user_id, market_code, bet_amount, commission, owner_earn, draw_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, b['market'], b['amount'], commission, owner_earn, b['date']))
    conn.commit()
    cur.close()
    conn.close()

def get_bet_history(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT draw_date, market_code, number, bet_type, amount FROM bets WHERE user_id=%s ORDER BY draw_date DESC LIMIT 10", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def calculate_commission(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(commission) FROM commissions WHERE user_id=%s", (user_id,))
    result = cur.fetchone()[0] or 0
    cur.close()
    conn.close()
    return round(result, 2)

def get_all_commissions():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, SUM(commission) FROM commissions 
        JOIN bets ON commissions.user_id = bets.user_id
        GROUP BY username ORDER BY SUM(commission) DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
