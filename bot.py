#!/usr/bin/env python3
import os
import logging
import random
import string
import pytz
import threading
from utils import check_group_winning
from db import clear_old_results,get_locked_bets
from db import USE_PG
from db import init_db
init_db()
from collections import OrderedDict
from telegram import CallbackQuery
from collections import defaultdict
from telegram.constants import ParseMode
from datetime import date, timedelta, datetime,time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from parser import parse_bet_text
from engine import calculate,STANDARD_ODDS
from db import (
    get_conn,
    get_commission_summary,
    get_bet_history,
    get_recent_bet_codes,
    delete_bet_and_commission
)
logger = logging.getLogger(__name__)

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 判断是否使用 Postgres 参数风格
USE_PG = bool(os.getenv("DATABASE_URL"))

ALLOWED_ADMIN_ID = 1392912618

async def show_personal_menu(update, context):
    keyboard = [
        [InlineKeyboardButton("🎯 输入中奖成绩", callback_data="input_result")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("请选择操作：", reply_markup=reply_markup)

async def handle_personal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ALLOWED_ADMIN_ID:
        await query.answer("❌ 你没有权限进行这个操作。", show_alert=True)
        return

    if query.data == "input_result":
        keyboard = [
            [InlineKeyboardButton("M", callback_data="result_market:M"), InlineKeyboardButton("K", callback_data="result_market:K")],
            [InlineKeyboardButton("T", callback_data="result_market:T"), InlineKeyboardButton("S", callback_data="result_market:S")],
            [InlineKeyboardButton("H", callback_data="result_market:H"), InlineKeyboardButton("E", callback_data="result_market:E")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("请选择 Market（市场）：", reply_markup=reply_markup)

    elif query.data.startswith("result_market:"):
        market = query.data.split(":")[1]
        context.user_data["result_market"] = market
        context.user_data["awaiting_result_input"] = True

        await query.edit_message_text(f"你选择了 {market}。\n请输入今日的中奖成绩（以空格分隔）：\n\n例如：1234 5678 9012")

async def handle_result_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_old_results(context.bot_data)
    user_id = update.effective_user.id
    print(f"收到输入: {update.message.text}")

    if user_id != ALLOWED_ADMIN_ID:
        await update.message.reply_text("❌ 你没有权限输入中奖成绩。")
        return

    if context.user_data.get("awaiting_result_input") and "result_market" in context.user_data:
        market = context.user_data["result_market"]
        text = update.message.text.strip()
        lines = text.splitlines()

        result_data = {
            "1st": "",
            "2nd": "",
            "3rd": "",
            "special": [],
            "consolation": []
        }

        for line in lines:
            if line.lower().startswith("1st:"):
                result_data["1st"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("2nd:"):
                result_data["2nd"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("3rd:"):
                result_data["3rd"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("special:"):
                result_data["special"] = line.split(":", 1)[1].strip().split()
            elif line.lower().startswith("consolation:"):
                result_data["consolation"] = line.split(":", 1)[1].strip().split()

        # 格式化为统一格式再保存
        result_text = (
            f"1st: {result_data['1st']}\n"
            f"2nd: {result_data['2nd']}\n"
            f"3rd: {result_data['3rd']}\n"
            f"Special: {' '.join(result_data['special'])}\n"
            f"Consolation: {' '.join(result_data['consolation'])}"
        )

        # 保存逻辑（你可以改成存数据库或文件）
        today_str = datetime.now().strftime("%d/%m")
        context.bot_data.setdefault("daily_results", {})  # 初始化
        context.bot_data["daily_results"][(today_str, market)] = result_text

        # 清理状态
        context.user_data.pop("awaiting_result_input", None)
        context.user_data.pop("result_market", None)

        await update.message.reply_text(f"{today_str} {market} 的中奖号码已记录：\n{result_text}")
    else:
        await update.message.reply_text("⚠️ 当前没有等待输入的成绩，或 Market 未设置。")

async def handle_check_winning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ 此功能仅限群组中使用。")
        return

    group_id = update.effective_chat.id
    today_str = datetime.now().strftime("%d/%m")
    daily_results = context.bot_data.get("daily_results", {})

    results = daily_results.get((today_str, "K"))  # 你可以动态传入 market，目前暂设为 K
    if not results:
        await update.message.reply_text("⚠️ 今日尚未记录中奖号码。")
        return

    # 拆解中奖号码
    prize_lines = results.splitlines()
    prizes = {"1st": [], "2nd": [], "3rd": [], "special": [], "consolation": []}
    for line in prize_lines:
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        if key.lower() in ("1st", "2nd", "3rd"):
            prizes[key.lower()].append(val.strip())
        elif key.lower() == "special":
            prizes["special"] = val.strip().split()
        elif key.lower() == "consolation":
            prizes["consolation"] = val.strip().split()

    # 获取锁注下注记录
    bets = get_locked_bets(group_id=group_id, date=today_str)
    if not bets:
        await update.message.reply_text("📭 今日无下注记录。")
        return

    winnings = []
    for bet in bets:
        number = bet["number"]
        bet_type = bet["bet_type"]
        market = bet["market"]
        amount = bet["amount"]

        odds = STANDARD_ODDS.get(market, {})
        matched = None

        for prize_type in ["1st", "2nd", "3rd", "special", "consolation"]:
            if number in prizes[prize_type]:
                matched = prize_type
                break

        if matched and bet_type in odds:
            payout = round(odds[bet_type] * amount, 2)
            winnings.append(f"✅ {number} 中 {matched.upper()}，赢得 RM{payout:.2f}")

    if winnings:
        result_text = "\n".join(winnings)
        await update.message.reply_text(f"🎉 今日中奖结果：\n{result_text}")
    else:
        await update.message.reply_text("😢 今日暂无中奖记录。")

async def handle_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 历史记录", callback_data="task:history")],
        [InlineKeyboardButton("💰 佣金报表", callback_data="task:commission")],
        [InlineKeyboardButton("🗑️ 删除下注", callback_data="task:delete")],
        [InlineKeyboardButton("🧾 查看重复", callback_data="task:check_duplicates")],
        [InlineKeyboardButton("📢 查看中奖", callback_data="task:check_winning")]
    ])
    await update.message.reply_text("📌 请选择任务操作：", reply_markup=keyboard)

PAGE_SIZE = 5
async def handle_task_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    group_id = str(query.message.chat.id)
    logger.info(f"[分页] 当前 data = {data}")
    await query.answer()

    if data == "task:history":
        # 初始化頁面為第0頁
        context.user_data["history_page"] = 0
        await show_history_date_buttons(query, context,group_id)

    elif data == "task:commission":
        today = datetime.now().date()
        start_date = today - timedelta(days=6)
        rows = get_commission_summary(start_date, today, group_id)

        if not rows:
            await query.message.reply_text("⚠️ 没有找到最近7天的佣金记录。")
            return

        lines = ["📊 佣金报表 (最近7天)\n"]
        for row in rows:
            lines.append(f"{row['day']}：总额 RM{row['total_amount']:.2f} / 佣金 RM{row['total_commission']:.2f}")
        await query.message.reply_text("\n".join(lines))

    elif data == "task:delete":
        context.user_data["delete_page"] = 0
        await show_delete_code_page(query, context, group_id)

    elif data.startswith("delete_page:"):
        try:
            page = int(data.split(":")[1])
        except:
            page = 0
        context.user_data["delete_page"] = max(0, page)

        logger.info(f"分页跳转至第 {page+1} 页")

        await query.answer(f"正在加载第 {page+1} 页…", show_alert=False)
        await show_delete_code_page(query, context, group_id)

    elif data.startswith("history_day:"):
        selected_date = data.split(":", 1)[1]  
        await show_bets_by_day(query, context,group_id, selected_date)

    elif data.startswith("delete_code:"):
        code = data.split(":", 1)[1]
        # 3. 调用新方法，一次性删除该 code 下的所有下注
        deleted_count = delete_bets_by_code(code, group_id)
        if deleted_count > 0:
            await query.edit_message_text(f"✅ 已删除 Code:{code} 下的所有 {deleted_count} 注单。")
        else:
            await query.edit_message_text("⚠️ 删除失败，Code 不存在或已删除。")

    elif data.startswith("confirm_delete:"):
        code = data.split(":", 1)[1]

        # 发出确认提示
        keyboard = [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"delete_code:{code}")],
            [InlineKeyboardButton("❌ 取消", callback_data="task:delete")]
        ]
        await query.edit_message_text(
            text=f"⚠️ 你确定要删除 Code:{code} 的单吗？",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "task:check_winning":
        if update.effective_chat.type == "private":
            await query.answer("❌ 请在群组中使用此功能", show_alert=True)
            return
        await handle_check_winning(update, context)

    elif query.data == "task:check_duplicates":
        await check_duplicate_numbers(update, context, group_id)

        return

async def show_delete_code_page(query, context, group_id):
    # ✅ 获取未被锁注的 code（内部已判断 19:00 锁注）
    all_codes = get_recent_bet_codes(group_id=group_id)  # 只会返回未锁定的

    if not all_codes:
        await query.message.edit_text("⚠️ 没有可显示的下注 Code。")
        return

    # ✅ 不再需要去重，get_recent_bet_codes 已确保唯一且未锁定
    total_codes = len(all_codes)

    # 分页设置
    PAGE_SIZE = 5
    page = context.user_data.get("delete_page", 0)
    offset = page * PAGE_SIZE
    current_codes = all_codes[offset: offset + PAGE_SIZE]

    if not current_codes:
        await query.message.edit_text("⚠️ 没有可显示的下注 Code。")
        return

    # 生成 code 按钮
    keyboard = [
        [InlineKeyboardButton(f"Code:{code}", callback_data=f"confirm_delete:{code}")]
        for code in current_codes
    ]

    # 分页按钮
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"delete_page:{page-1}"))
    if offset + PAGE_SIZE < total_codes:
        buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"delete_page:{page+1}"))
    if buttons:
        keyboard.append(buttons)

    # 发送消息
    await query.message.edit_text(
        f"🗑️ 请选择要删除的下注 Code：\n\n"
        f"✅ 正在显示第 {page + 1} 页 / 共 {(total_codes + PAGE_SIZE - 1) // PAGE_SIZE} 页",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def get_bet_count_for_code(code, group_id):
    conn = get_conn()
    c = conn.cursor()
    try:
        if USE_PG:
            c.execute(
                "SELECT COUNT(*) FROM bets WHERE code=%s AND group_id=%s",
                (code, group_id)
            )
        else:
            c.execute(
                "SELECT COUNT(*) FROM bets WHERE code=? AND group_id=?",
                (code, group_id)
            )
        return c.fetchone()[0]
    except Exception as e:
        logger.error(f"❌ 获取下注数量失败: {e}")
        return 0
    finally:
        conn.close()

def delete_bets_by_code(code, group_id):
    conn = get_conn()
    c = conn.cursor()
    try:
        # 查询下注日期
        if USE_PG:
            c.execute("SELECT bet_date FROM bets WHERE code=%s AND group_id=%s", (code, group_id))
        else:
            c.execute("SELECT bet_date FROM bets WHERE code=? AND group_id=?", (code, group_id))

        row = c.fetchone()
        if not row:
            return 0

        from datetime import datetime, time
        import pytz

        bet_datetime = row[0]
        if isinstance(bet_datetime, str):
            bet_datetime = datetime.fromisoformat(bet_datetime)

        if isinstance(bet_datetime, datetime):
            bet_date = bet_datetime.date()
        else:
            bet_date = bet_datetime

        # 马来西亚时区 + 获取当前时间
        tz = pytz.timezone("Asia/Kuala_Lumpur")
        now = datetime.now(tz)
        lock_datetime = tz.localize(datetime.combine(bet_date, time(19, 0)))  # 晚上 7 点锁注

        # ✅ 只要现在超过下注当晚 7 点，就禁止删除
        if now >= lock_datetime:
            logger.warning("🔒 尝试删除已锁注的下注单，拒绝删除。")
            return 0

        # 正常删除
        if USE_PG:
            c.execute("DELETE FROM bets WHERE code=%s AND group_id=%s", (code, group_id))
        else:
            c.execute("DELETE FROM bets WHERE code=? AND group_id=?", (code, group_id))

        deleted = c.rowcount
        conn.commit()
        return deleted

    except Exception as e:
        logger.error(f"❌ 删除下注失败: {e}")
        return 0
    finally:
        conn.close()

async def show_history_date_buttons(query, context, group_id):
    today = datetime.now().date()
    
    keyboard = []
    row = []

    for i in range(7):
        date_obj = today - timedelta(days=i)
        button = InlineKeyboardButton(
            text=date_obj.strftime("%d/%m"),
            callback_data=f"history_day:{date_obj.strftime('%Y-%m-%d')}"
        )
        row.append(button)

        # 每3个按钮组成一行
        if (i + 1) % 3 == 0:
            keyboard.append(row)
            row = []

    # 剩下不满3个的按钮行也添加进去
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📅 请选择要查看下注记录的日期：",
        reply_markup=reply_markup
    )

async def show_bets_by_day(query, context, group_id, selected_date):
    date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()
    bets = get_bet_history(date_obj, date_obj, group_id)

    if not bets:
        await query.edit_message_text("⚠️ 你在该日没有下注记录。")
        return

    grouped = OrderedDict()
    for b in bets:
        grouped.setdefault(b["code"], []).append(b)

    lines = []

    for code, code_bets in grouped.items():
        date = code_bets[0]['date']
        market = code_bets[0].get("market", "MKT")
        total_amount = 0
        number_map = {}

        # 统计每个号码下的下注类型与金额
        for b in code_bets:
            if "number" not in b or "bet_type" not in b or "amount" not in b:
                logger.warning(f"无效下注数据: {b}")
                continue

            number = b["number"]
            bet_type = b["bet_type"]
            amount = float(b["amount"])
            market_count = len(b.get("market", "M").split(","))  # ✅ 计算market数量
            total_amount += amount * market_count  # ✅ 加上市场倍数

            if number not in number_map:
                number_map[number] = {}
            if bet_type not in number_map[number]:
                number_map[number][bet_type] = 0
            number_map[number][bet_type] += amount

        number_lines = []
        for number, type_dict in number_map.items():
            type_str = "/".join([f"{int(amount)}{bet_type}" for bet_type, amount in sorted(type_dict.items())])
            number_lines.append(f"{number}-{type_str}")

        # 拼接文本
        lines.append(f"📅 {date}")
        lines.append(f"{market}")
        lines.append(" ".join(number_lines))
        lines.append(f"Total {int(total_amount)}")
        lines.append("-------------------------")

    text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="HTML")

async def handle_bet_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        return
    text = update.message.text
    try:
        bets = parse_bet_text(text)
    except ValueError as e:
        await update.message.reply_text(f"❌ 格式错误：{e}")
        return

    # 计算汇总和内嵌写回每笔
    summary = calculate(bets)
    total = summary['total_amount']
    potential = summary['total_potential']
    commission = summary['total_commission']

    # 缓存待确认注单
    context.user_data['pending_bets'] = bets

    # 发送确认按钮
    keyboard = [[InlineKeyboardButton("✅ 确认下注", callback_data="confirm_bet")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"总额 RM{total:.2f}，最多可赢 RM{potential:.2f}\n"
        f"代理佣金 RM{commission:.2f}，确认下注吗？", reply_markup=reply_markup
    )

async def check_duplicate_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        # 获取马来西亚当前日期
        tz = pytz.timezone("Asia/Kuala_Lumpur")
        today = datetime.now(tz).date()

        if USE_PG:
            c.execute("""
                SELECT bet_date, number, market, bet_type,COUNT(*)
                FROM bets
                WHERE group_id = %s AND bet_date = %s
                GROUP BY bet_date, number, market, bet_type
                HAVING COUNT(*) > 1
                ORDER BY bet_date DESC
            """, (group_id, today))
        else:
            c.execute("""
                SELECT bet_date, number, market, bet_type,COUNT(*)
                FROM bets
                WHERE group_id = ? AND bet_date = ?
                GROUP BY bet_date, number, market, bet_type
                HAVING COUNT(*) > 1
                ORDER BY bet_date DESC
            """, (group_id, today))

        rows = c.fetchall()
        if not rows:
            await update.callback_query.answer("✅ 没有发现重复下注号码", show_alert=True)
        else:
            text = "⚠️ 重复下注号码如下：\n"
            for row in rows:
                date, number, market,bet_type ,count = row
                text += f"{date} - {market} - {number} - {bet_type}（{count}次）\n"
            await update.callback_query.message.reply_text(text)

    except Exception as e:
        logger.error(f"❌ 检查重复号码出错: {e}")
        await update.callback_query.answer("❌ 检查失败，请稍后再试", show_alert=True)
    finally:
        conn.close()

async def handle_confirm_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # 1. 给用户一个点击反馈（短暂吐司）
    await query.answer(text="下注处理中…", show_alert=False)

    # 2. 从缓存读取待确认注单
    bets = context.user_data.get('pending_bets')
    if not bets:
        # 如果找不到，给一个弹窗提示
        await query.answer(
            text="⚠️ 未找到待确认的下注记录，请重新下注！",
            show_alert=True
        )
        return

    tz = pytz.timezone("Asia/Kuala_Lumpur")
    now = datetime.now(tz)
    today = now.date()

    # 提取下注的日期（格式为 DD/MM）
    bet_date = datetime.strptime(bets[0]["date"], "%Y-%m-%d").date()
    lock_time = datetime.combine(bet_date, time(19, 0)).replace(tzinfo=tz)

    if now >= lock_time:
        await query.answer(
            text="⛔️ 此下注日期已锁注（每日19:00后不接受当日及更早日期的下注）",
            show_alert=True
        )
        return

    # 3. 生成删除用 Code（格式：YYMMDD + 3 随机大写字母）
    date_str = datetime.now().strftime('%y%m%d')
    rand_letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    delete_code = f"{date_str}{rand_letters}"
    group_id = query.message.chat.id

    # 4. 写入数据库
    # 1. 把 USE_PG 和 sql 定义提到函数最开头（或者模块顶层就定义一次）
    try:
        conn = get_conn()
        cursor = conn.cursor()
        if USE_PG:
            sql = (
                "INSERT INTO bets "
                "(agent_id, group_id, bet_date, market, number, bet_type, mode, amount, potential_win, commission, code) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
        else:
            sql = (
                "INSERT INTO bets "
                "(agent_id, group_id, bet_date, market, number, bet_type, mode, amount, potential_win, commission, code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            )

        for bet in bets:
            # 把 market 列表统一转成字符串
            market_str = ','.join(str(m) for m in bet['markets'])
            params = (
                query.from_user.id,
                group_id,
                bet['date'],
                market_str,                  # 这里用 market_str
                bet['number'],
                bet['type'],
                bet.get('mode') or '',       # 如果 mode 可能为 None，给个默认
                bet['amount'],
                bet['potential_win'],
                bet['commission'],
                delete_code
            )
                # 真正执行
            cursor.execute(sql, params)
        # 3. 循环外 commit
        conn.commit()

    except Exception as e:
        logger.error(f"❌ 确认下注写库出错：{e}")
        # 给用户明确的失败提示
        await query.answer(
            text="⚠️ 系统错误，下注失败，请稍后重试",
            show_alert=True
        )
        return
    finally:
        conn.close()

# 4. 成功后继续下面的 edit_message_reply_markup + reply_text...


    # 5. 移除原消息的确认按钮，但保留原文案
    await query.edit_message_reply_markup(reply_markup=None)

    # 6. 发送新的成功提示消息
    await query.message.reply_text(
        f"✅ 下注成功！\n"
        f"Code：{delete_code}\n"
    )

    # 7. 清空缓存
    context.user_data.pop('pending_bets', None)

def main():

    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error('BOT_TOKEN 未设置')
        return
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & filters.ChatType.PRIVATE,handle_result_input))
    app.add_handler( MessageHandler( filters.TEXT & ~filters.Regex(r'^/'), handle_bet_text)) 
    app.add_handler(CallbackQueryHandler(handle_confirm_bet, pattern="^confirm_bet$"))
    app.add_handler(CallbackQueryHandler(handle_task_buttons, pattern="^task:|^history_day:|^delete_code:|^confirm_delete:|^commission:|^delete_page:"))
    app.add_handler(CommandHandler("task", handle_task_menu))
    app.add_handler(CommandHandler("start", show_personal_menu))
    app.add_handler(CallbackQueryHandler(handle_personal_menu))
    app.add_handler(CallbackQueryHandler(handle_personal_menu, pattern="^input_result$"))
    app.add_handler(CallbackQueryHandler(handle_personal_menu, pattern="^result_market:"))
    
    app.run_polling()

if __name__ == '__main__':
    main()
