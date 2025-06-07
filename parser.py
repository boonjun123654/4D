from datetime import datetime

def parse_bet_input(text, user_id, username):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("请输入格式：日期 + 市场 + 下注内容")

    date_line = lines[0]
    market_line = lines[1].upper()
    content_lines = lines[2:]

    # 日期支持多天，用 & 分隔
    date_list = [datetime.strptime(d, "%d/%m/%Y").date() for d in date_line.split("&")]

    # 市场支持多个，例如 MKT = M, K, T
    market_map = {
        "M": "Magnum",
        "K": "Damacai",
        "T": "Toto",
        "S": "Singapore",
        "H": "GrandDragon",
        "L": "9Lotto"
    }
    market_codes = list(market_line)
    for code in market_codes:
        if code not in market_map:
            raise ValueError(f"未知市场代码：{code}")

    bet_entries = []
    for line in content_lines:
        if "-" not in line:
            raise ValueError("下注行必须包含 '-' 符号")

        number, detail = line.split("-", 1)
        number = number.strip()
        parts = detail.lower().split()

        is_box = "box" in parts
        is_ibox = "ibox" in parts
        parts = [p for p in parts if p not in ["box", "ibox"]]

        # 处理如：2b 1s
        for part in parts:
            if len(part) < 2:
                continue
            amount = float(part[:-1])
            bet_type = part[-1].upper()
            if bet_type not in ["B", "S", "A", "C"]:
                raise ValueError(f"未知下注类型：{bet_type}")

            for date in date_list:
                for market_code in market_codes:
                    bet_entries.append({
                        "user_id": user_id,
                        "username": username,
                        "market_code": market_code,
                        "number": number,
                        "bet_type": bet_type,
                        "is_box": is_box,
                        "is_ibox": is_ibox,
                        "amount": amount,
                        "draw_date": date
                    })
    return bet_entries