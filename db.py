import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def save_bets(bet_list):
    conn = get_connection()
    cur = conn.cursor()
    for bet in bet_list:
        cur.execute("""
            INSERT INTO bets (user_id, username, market_code, number, bet_type, is_box, is_ibox, amount, draw_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            bet["user_id"],
            bet["username"],
            bet["market_code"],
            bet["number"],
            bet["bet_type"],
            bet["is_box"],
            bet["is_ibox"],
            bet["amount"],
            bet["draw_date"]
        ))
    conn.commit()
    cur.close()
    conn.close()
