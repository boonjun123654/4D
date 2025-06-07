import re
from datetime import datetime
from itertools import permutations

# 奖金赔率配置（部分略）
PAYOUTS = {
    "MKTS": {
        "B": 2750,
        "S": 3850,
        "A": 726,
        "C": 242
    },
    "HL": {
        "B": 3045,
        "S": 4095,
        "A": 740.25,
        "C": 246.75
    }
}

COMMISSION_RATE = {
    "MKTS": 0.26,
    "HL": 0.19
}

def parse_bet_input(text, user_id, username):
    lines = text.strip().split("\n")
    all_bets = []
    current_date = None
    market_codes = []

    for line in lines:
        line = line.strip()

        # 日期行
        if re.match(r"\d{2}/\d{2}/\d{4}(&\d{2}/\d{2}/\d{4})*", line):
            current_date = line.strip()
            continue

        # 市场代码
        if re.match(r"^[MKTSHL]+$", line):
            market_codes = list(line)
            continue

        # 下注行
        if "-" in line:
            try:
                number_part, rest = line.split("-", 1)
                number = number_part.strip()
                if not re.match(r"^\d{4}$", number):
                    raise ValueError("号码必须是4位数字")

                bets = rest.strip().split()
                types = []
                box_mode = None
                for b in bets:
                    if b.lower() in ["ibox", "box"]:
                        box_mode = b.lower()
                    elif re.match(r"\d+[BSAC]", b.upper()):
                        types.append(b.upper())
                    else:
                        raise ValueError(f"未知下注类型：{b}")

                for date_str in current_date.split("&"):
                    try:
                        bet_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                    except Exception:
                        raise ValueError(f"无效日期格式：{date_str}")

                    for mkt in market_codes:
                        for t in types:
                            amount = int(re.findall(r"\d+", t)[0])
                            bet_type = re.findall(r"[BSAC]", t)[0]

                            # 默认组合数为1
                            combination_count = 1
                            win_amount = 0

                            if box_mode == "ibox":
                                combination_count = len(set(permutations(number)))
                                if bet_type in ["B", "S"]:
                                    win_amount = get_ibox_payout(number, mkt, bet_type)
                            elif box_mode == "box":
                                combination_count = len(set(permutations(number)))
                                if bet_type in ["B", "S"]:
                                    win_amount = PAYOUTS[mkt][bet_type]
                            else:
                                win_amount = PAYOUTS[mkt][bet_type]

                            bet_record = {
                                "user_id": user_id,
                                "username": username,
                                "date": bet_date.strftime("%Y-%m-%d"),
                                "market": mkt,
                                "number": number,
                                "type": bet_type,
                                "amount": amount,
                                "box_mode": box_mode,
                                "combo": combination_count,
                                "win_amount": win_amount
                            }
                            all_bets.append(bet_record)
            except Exception as e:
                raise Exception(f"解析失败: '{line}' → {e}")

    return all_bets


def get_ibox_payout(number, market, bet_type):
    combo_count = len(set(permutations(number)))
    base_payout = PAYOUTS[market][bet_type]
    if combo_count == 24:
        return round(base_payout / 24, 2)
    elif combo_count == 12:
        return round(base_payout / 12, 2)
    elif combo_count == 6:
        return round(base_payout / 6, 2)
    elif combo_count == 4:
        return round(base_payout / 4, 2)
    else:
        return round(base_payout / combo_count, 2)
