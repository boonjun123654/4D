# parser.py

import re
from datetime import datetime
from typing import List, Dict

# 支持的 market code
VALID_MARKETS = {"M", "K", "T", "S", "H", "E"}

def parse_bet_text(text: str, default_year: int = 2025) -> List[Dict]:
    """
    将下注文本拆成多笔注单。
    
    文本格式示例：
        08/06
        MKT
        1526-1B 1S ibox
        1234-2C box 5A

    返回示例：
    [
      {
        "date": "2025-06-08",
        "markets": ["M","K","T"],
        "number": "1526",
        "type": "B",
        "mode": "ibox",
        "amount": 1
      },
      {
        "date": "2025-06-08",
        "markets": ["M","K","T"],
        "number": "1526",
        "type": "S",
        "mode": "ibox",
        "amount": 1
      },
      {
        "date": "2025-06-08",
        "markets": ["M","K","T"],
        "number": "1234",
        "type": "C",
        "mode": "box",
        "amount": 2
      },
      {
        "date": "2025-06-08",
        "markets": ["M","K","T"],
        "number": "1234",
        "type": "A",
        "mode": "box",
        "amount": 5
      }
    ]
    """
    # 1. 分行并去除空行
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("格式错误：至少需要日期、市场行、下注行")

    # 2. 解析日期
    date_match = re.match(r"^(\d{1,2})/(\d{1,2})$", lines[0])
    if not date_match:
        raise ValueError(f"无效日期格式：{lines[0]}")
    day, month = map(int, date_match.groups())
    date_obj = datetime(default_year, month, day)
    date_str = date_obj.strftime("%Y-%m-%d")

    # 3. 解析市场代码
    market_line = lines[1].replace(" ", "").upper()
    markets = [c for c in market_line if c in VALID_MARKETS]
    if not markets:
        raise ValueError(f"未识别任何有效市场代码：{lines[1]}")

    # 4. 遍历下注行，拆出每笔注单
    bets: List[Dict] = []
    for line in lines[2:]:
        tokens = line.split()
        # 检查是否有特殊模式 ibox/box
        mode = None
        if tokens[-1].lower() in ("ibox", "box"):
            mode = tokens[-1].lower()
            tokens = tokens[:-1]

        current_number = None
        for tok in tokens:
            # 格式：号码-金额类型，例如 "1526-1B"
            m_full = re.match(r"^(\d{1,4})-(\d+)([BSAC])$", tok, re.IGNORECASE)
            if m_full:
                num, amt, t = m_full.groups()

                if mode and t.upper() not in ("B", "S"):
                    raise ValueError(f"模式“{mode}”只能用于 B/S 类型下注，无法用于 {t.upper()}。")

                current_number = num.zfill(4)
                bets.append({
                    "date": date_str,
                    "markets": markets,
                    "number": current_number,
                    "type": t.upper(),
                    "mode": mode,
                    "amount": int(amt)
                })
                continue

            # 格式：金额类型，例如 "1S"
            m_part = re.match(r"^(\d+)([BSAC])$", tok, re.IGNORECASE)
            if m_part:
                if current_number is None:
                    raise ValueError(f"未指定号码，无法解析：{tok}")
                amt, t = m_part.groups()
                if mode and t.upper() not in ("B", "S"):
                    raise ValueError(f"模式“{mode}”只能用于 B/S 类型下注，无法用于 {t.upper()}。")
                bets.append({
                    "date": date_str,
                    "markets": markets,
                    "number": current_number,
                    "type": t.upper(),
                    "mode": mode,
                    "amount": int(amt)
                })
                continue

            # 跳过无法识别的 token
            # raise ValueError(f"无法解析的 token：{tok}")

    return bets

# ---------- 本地测试 ----------
if __name__ == "__main__":
    samples = [
        """\
08/06
MKT
1526-1B 1S ibox
""",
        """\
09/06
MS
1234-2C box 5A
"""
    ]
    for txt in samples:
        print("输入：")
        print(txt)
        print("输出：")
        print(parse_bet_text(txt))
        print("-" * 30)
