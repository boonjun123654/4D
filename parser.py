import re
from datetime import datetime

def parse_bet_message(message_text, user_id):
    """
    输入：
    07/06/2025
    MKT
    1234-1B 1S ibox
    2234-2B 2C
    输出：
    List[dict] → 每一笔下注记录
    """

    lines = message_text.strip().splitlines()
    if len(lines) < 3:
        return []

    date_line = lines[0].strip()
    market_line = lines[1].strip().upper()
    bet_lines = lines[2:]

    # 多日期支持（07/06/2025 & 08/06/2025）
    dates = [d.strip() for d in date_line.split("&")]
    markets = list(market_line)

    bets = []

    for line in bet_lines:
        if "-" not in line:
            continue
        number_part, bet_part = line.split("-", 1)
        number = number_part.strip()

        bet_items = bet_part.strip().split()
        box_type = None
        amounts = {}

        for item in bet_items:
            item = item.strip().upper()
            if item in ["IBOX", "BOX"]:
                box_type = item.lower()
            else:
                match = re.match(r"(\d+)([ABCS])", item)
                if match:
                    amt, btype = match.groups()
                    amounts[btype] = int(amt)

        for date in dates:
            for market in markets:
                for btype, amount in amounts.items():
                    bets.append({
                        "user_id": user_id,
                        "date": date,
                        "market": market,
                        "number": number,
                        "bet_type": btype,
                        "amount": amount,
                        "box_type": box_type,
                        "created_at": datetime.now()
                    })

    return bets
