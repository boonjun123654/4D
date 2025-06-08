import re
from datetime import datetime
from itertools import permutations

# 奖金赔率配置
PAYOUTS = {
    "MKTS": {"B": 2750, "S": 3850, "A": 726, "C": 242},
    "HL": {"B": 3045, "S": 4095, "A": 740.25, "C": 246.75}
}

# iBox 奖金配置
ODDS = {
    "MKTS": {
        "B": {"1": 2750, "2": 1100, "3": 550, "S": 220, "C": 66},
        "S": {"1": 3850, "2": 2200, "3": 1100},
        "A": 726,
        "C": 242,
        "iBox": {
            24: {"B": {"1": 114.58}, "S": {"1": 160.42}},
            12: {"B": {"1": 229.17}, "S": {"1": 320.83}},
            6:  {"B": {"1": 458.33}, "S": {"1": 641.67}},
            4:  {"B": {"1": 687.50}, "S": {"1": 962.50}}
        }
    },
    "HL": {
        "B": {"1": 3045, "2": 1050, "3": 525, "S": 210, "C": 63},
        "S": {"1": 4095, "2": 2100, "3": 1050},
        "A": 740.25,
        "C": 246.75,
        "iBox": {
            24: {"B": {"1": 126.88}, "S": {"1": 170.63}},
            12: {"B": {"1": 253.75}, "S": {"1": 341.25}},
            6:  {"B": {"1": 507.50}, "S": {"1": 682.50}},
            4:  {"B": {"1": 761.25}, "S": {"1": 1023.75}}
        }
    }
}

COMMISSION_RATE = {"MKTS": 0.26, "HL": 0.19}

def get_comb_count(number: str) -> int:
    return len(set(permutations(number)))

def get_box_multiplier(number: str) -> int:
    digits = list(number)
    unique_digits = set(digits)
    count = len(unique_digits)
    if count == 4:
        return 24
    elif count == 3:
        return 12
    elif count == 2:
        if digits.count(digits[0]) == 2:
            return 6
        else:
            return 4
    else:
        return 1

def validate_number_format(number: str) -> bool:
    return re.fullmatch(r"\d{4}", number) is not None

def get_ibox_payout(number, market, bet_type):
    combo_count = get_comb_count(number)
    base_payout = PAYOUTS[market][bet_type]
    return round(base_payout / combo_count, 2)

def parse_bet_input(text, user_id, username):
    lines = text.strip().split("\n")
    all_bets = []
    current_date = None
    market_codes = []

    for line in lines:
        line = line.strip()

        if re.match(r"\d{2}/\d{2}/\d{4}(&\d{2}/\d{2}/\d{4})*", line):
            current_date = line.strip()
            continue

        if re.match(r"^[MKTSHL]+$", line):
            market_codes = list(line)
            continue

        if "-" in line:
            try:
                number_part, rest = line.split("-", 1)
                number = number_part.strip()
                if not validate_number_format(number):
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
                    bet_date = datetime.strptime(date_str, "%d/%m/%Y").date()

                    for mkt in market_codes:
                        for t in types:
                            amount = int(re.findall(r"\d+", t)[0])
                            bet_type = re.findall(r"[BSAC]", t)[0]

                            combo = 1
                            win_amount = PAYOUTS[mkt][bet_type]

                            if box_mode == "ibox":
                                combo = get_comb_count(number)
                                if bet_type in ["B", "S"]:
                                    win_amount = get_ibox_payout(number, mkt, bet_type)

                            elif box_mode == "box":
                                combo = get_box_multiplier(number)
                                amount *= combo  # ✅ 关键修改：金额乘以组合数
                                # win_amount 不变，维持原赔率

                            bet_record = {
                                "user_id": user_id,
                                "username": username,
                                "date": bet_date.strftime("%Y-%m-%d"),
                                "market": mkt,
                                "number": number,
                                "type": bet_type,
                                "amount": amount,
                                "box_mode": box_mode,
                                "combo": combo,
                                "win_amount": win_amount
                            }
                            all_bets.append(bet_record)
            except Exception as e:
                raise Exception(f"解析失败: '{line}' → {e}")
    return all_bets
