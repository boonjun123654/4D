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

ODDS = {
    "MKTS": {
        "B": {"1": 2750, "2": 1100, "3": 550, "S": 220, "C": 66},
        "S": {"1": 3850, "2": 2200, "3": 1100},
        "A": 726,
        "C": 242,
        "iBox": {
            24: {"B": {"1": 114.58, "2": 45.83, "3": 22.92, "S": 9.17, "C": 2.75}, "S": {"1": 160.42, "2": 82.50, "3": 41.25}},
            12: {"B": {"1": 229.17, "2": 91.67, "3": 45.83, "S": 18.33, "C": 5.50}, "S": {"1": 320.83, "2": 165.00, "3": 82.50}},
            6:  {"B": {"1": 458.33, "2": 183.33, "3": 91.67, "S": 36.67, "C": 11.00}, "S": {"1": 641.67, "2": 330.00, "3": 165.00}},
            4:  {"B": {"1": 687.50, "2": 275.00, "3": 137.50, "S": 55.00, "C": 16.50}, "S": {"1": 962.50, "2": 495.00, "3": 247.50}}
        }
    },
    "HL": {
        "B": {"1": 3045, "2": 1050, "3": 525, "S": 210, "C": 63},
        "S": {"1": 4095, "2": 2100, "3": 1050},
        "A": 740.25,
        "C": 246.75,
        "iBox": {
            24: {"B": {"1": 126.88, "2": 43.75, "3": 21.88, "S": 8.75, "C": 2.63}, "S": {"1": 170.63, "2": 87.50, "3": 43.75}},
            12: {"B": {"1": 253.75, "2": 87.50, "3": 43.75, "S": 17.50, "C": 5.25}, "S": {"1": 341.25, "2": 175.00, "3": 87.50}},
            6:  {"B": {"1": 507.50, "2": 175.00, "3": 87.50, "S": 35.00, "C": 10.50}, "S": {"1": 682.50, "2": 350.00, "3": 175.00}},
            4:  {"B": {"1": 761.25, "2": 262.50, "3": 131.25, "S": 52.50, "C": 15.75}, "S": {"1": 1023.75, "2": 525.00, "3": 262.50}}
        }
    }
}

# 计算组合数（ibox/box 用）
def get_comb_count(number: str) -> int:
    perms = set(permutations(number))
    return len(perms)

# 获取后三位（用于 A/C 类型）
def last3(number: str) -> str:
    return number[-3:]

# 判断 box 模式下是否中奖
def is_box_hit(bet_number: str, draw_number: str) -> bool:
    return draw_number in {"".join(p) for p in permutations(bet_number)}

# 验证号码格式
def validate_number_format(number: str) -> bool:
    return re.fullmatch(r"\d{4}", number) is not None

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

# parser.py

def get_box_multiplier(number: str) -> int:
    """
    根据号码判断 box 组合数（用于计算 box 模式下注总额）
    """
    digits = list(number)
    unique_digits = set(digits)
    count = len(unique_digits)
    if count == 4:
        return 24
    elif count == 3:
        # 两个数字重复，如 2234（ABBC）：12 种组合
        return 12
    elif count == 2:
        if digits.count(digits[0]) == 2:
            # 形如 2233：6 种组合
            return 6
        else:
            # 三个一样如 2223（AAAB）：4 种组合
            return 4
    else:
        # 四个一样（如 1111），只算一种
        return 1


