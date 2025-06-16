from db import get_locked_bets_for_date

def check_group_winning(chat_id, results_data, date_str):
    results = {
        key[1]: results_data[key] 
        for key in results_data if key[0] == date_str
    }
    if not results:
        return []

    bets = get_locked_bets_for_date(chat_id, date_str)
    winnings = []

    for bet in bets:
        number = bet.number
        market = bet.market
        bet_type = bet.bet_type
        amount = bet.amount
        key = (date_str, market)

        if key not in results_data:
            continue

        result_text = results_data[key]
        for line in result_text.splitlines():
            if ":" in line:
                title, numbers = line.split(":")
                numbers = numbers.strip().split()
                if number in numbers:
                    prize = title.strip()
                    winnings.append({
                        "number": number,
                        "prize_type": prize,
                        "amount": amount * 1.0  # 可根据 prize 类型给不同赔率
                    })

    return winnings
