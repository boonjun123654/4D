# engine.py

import math
from collections import Counter
from typing import List, Dict

# 标准赔率（RM1）── 
STANDARD_ODDS = {
    # MKTS 市场（M, K, T, S）
    **{m: {"B": 2750, "S": 3850, "A": 726,   "C": 242} for m in ("M","K","T","S")},
    # H/L 市场（H, L）
    **{m: {"B": 3045, "S": 4095, "A": 740.25,"C": 246.75} for m in ("H","L")},
}

# 代理抽水比例 :contentReference[oaicite:1]{index=1}
COMMISSION_RATES = {
    "MKTS": 0.26,
    "HL":   0.19,
}

def _combination_count(number: str) -> int:
    """计算 4 位数字的全排列组合数：4! / ∏(count(d)!)"""
    cnt = Counter(number)
    comb = math.factorial(4)
    for c in cnt.values():
        comb //= math.factorial(c)
    return comb

def _commission_rate_for_market(market: str) -> float:
    """返回单个 market 的抽水比例"""
    return COMMISSION_RATES["MKTS"] if market in ("M","K","T","S") else COMMISSION_RATES["HL"]

def calculate(bets: List[Dict]) -> Dict:
    """
    对 parser.parse_bet_text 拆出的注单列表进行计算。

    修改每个 bet dict，新增字段：
      - comb
      - stake
      - potential_win
      - commission

    并返回汇总：
      {
        "total_amount": ...,
        "total_potential": ...,
        "total_commission": ...
      }
    """
    total_amount = 0.0
    total_potential = 0.0
    total_commission = 0.0

    for bet in bets:
        number  = bet["number"]
        btype   = bet["type"]
        amt     = bet["amount"]
        mode    = bet.get("mode")
        markets = bet["markets"]

        # 1. 组合数
        comb = _combination_count(number)

        # 2. 单市场扣款（stake_per_market）
        if mode == "box":
            # box：每注全排列
            stake_per_market = amt * comb
        else:
            # 普通 & ibox：只扣原金额
            stake_per_market = amt

        # 3. 单市场最大可赢（potential_per_market）
        if "H" in markets:
            odds_market = "H"
        elif "L" in markets:
            odds_market = "L"
        else:
            odds_market = "M"
        std_odds = STANDARD_ODDS[odds_market][btype]

        if mode == "ibox":
            # ibox：赔率按组合数平均
            potential_per_market = std_odds / comb * amt
        elif mode == "box":
            # box：虽支付全排列的金额（stake_per_market），
            #     但赢奖仅按原下注额计算
            potential_per_market = std_odds * amt
        else:
            # 普通模式：按实际下在每市的金额计算
            potential_per_market = std_odds * stake_per_market

        # 4. 多市场累加
        n_markets = len(markets)
        bet_total_stake     = stake_per_market * n_markets
        bet_total_potential = potential_per_market * n_markets

        # 5. 佣金 = ∑(每市场 stake_per_market × rate)
        commission = sum(
            stake_per_market * _commission_rate_for_market(m)
            for m in markets
        )

        # 6. 累计到总数
        total_amount    += bet_total_stake
        total_potential += potential_per_market
        total_commission+= commission

        # 7. 回写回 bet dict
        bet["comb"]          = comb
        bet["stake"]         = stake_per_market
        bet["potential_win"] = bet_total_potential
        bet["commission"]    = commission

    return {
        "total_amount":     total_amount,
        "total_potential":  total_potential,
        "total_commission": total_commission,
    }
