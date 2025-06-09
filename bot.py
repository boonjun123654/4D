#!/usr/bin/env python3
import os
import logging
import random
import string
import threading
from collections import defaultdict
from telegram.constants import ParseMode
from datetime import date, timedelta, datetime
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
from engine import calculate
from db import conn, cursor

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 判断是否使用 Postgres 参数风格
USE_PG = bool(os.getenv("DATABASE_URL"))

async def show_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📜 历史记录", callback_data="task:history"),
            InlineKeyboardButton("💰 佣金报表", callback_data="task:commission")
        ],
        [
            InlineKeyboardButton("🗑 删除下注", callback_data="task:delete")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔧 请选择你要执行的任务：", reply_markup=reply_markup)

async def handle_task_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    task = query.data.split(":")[1]

    if task == "history":
        await cmd_history(update, context)
    elif task == "commission":
        await cmd_commission(update, context)
    elif task == "delete":
        user_id = query.from_user.id
        recent_codes = db.get_recent_bet_codes(user_id, limit=10)

        if not recent_codes:
            await query.message.reply_text("你最近没有下注记录。")
            return

        keyboard = []
        for code in recent_codes:
            keyboard.append([
                InlineKeyboardButton(f"删除 {code}", callback_data=f"delete_code:{code}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("请选择要删除的下注 Code：", reply_markup=reply_markup)

def get_recent_bet_codes(user_id, limit=5):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT code FROM bets
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]


async def handle_bet_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # 3. 生成删除用 Code（格式：YYMMDD + 3 随机大写字母）
    date_str = datetime.now().strftime('%y%m%d')
    rand_letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    delete_code = f"{date_str}{rand_letters}"

    # 4. 写入数据库
    USE_PG = bool(os.getenv("DATABASE_URL"))
    for bet in bets:
        params = (
            query.from_user.id,
            bet['date'],
            ','.join(bet['markets']),
            bet['number'],
            bet['type'],
            bet.get('mode'),
            bet['amount'],
            bet['potential_win'],
            bet['commission'],
            delete_code
        )
        if USE_PG:
            sql = (
                "INSERT INTO bets "
                "(agent_id,bet_date,market,number,bet_type,mode,amount,potential_win,commission,code) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
        else:
            sql = (
                "INSERT INTO bets "
                "(agent_id,bet_date,market,number,bet_type,mode,amount,potential_win,commission,code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)"
            )
        cursor.execute(sql, params)
    conn.commit()

    # 5. 移除原消息的确认按钮，但保留原文案
    await query.edit_message_reply_markup(reply_markup=None)

    # 6. 发送新的成功提示消息
    await query.message.reply_text(
        f"✅ 下注成功！\n"
        f"Code：{delete_code}\n"
        f"如需删除，请使用：/delete {delete_code}"
    )

    # 7. 清空缓存
    context.user_data.pop('pending_bets', None)


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("请提供删除 Code，例如：/delete 250608ABC")
        return

    code = args[0]

    # 先检查是否存在该注单
    if USE_PG:
        cursor.execute("SELECT COUNT(*) FROM bets WHERE code = %s", (code,))
    else:
        cursor.execute("SELECT COUNT(*) FROM bets WHERE code = ?", (code,))
    count = cursor.fetchone()[0]

    if not count:
        await update.message.reply_text(f"⚠️ 未找到对应 Code 的下注记录。")
        return

    # 删除下注 + 删除佣金
    if USE_PG:
        cursor.execute("DELETE FROM bets WHERE code = %s", (code,))
        cursor.execute("DELETE FROM commissions WHERE code = %s", (code,))
    else:
        cursor.execute("DELETE FROM bets WHERE code = ?", (code,))
        cursor.execute("DELETE FROM commissions WHERE code = ?", (code,))
    conn.commit()

    await update.message.reply_text("✅ 注单记录及佣金已删除。")

async def handle_delete_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":")[1]

    # 删除下注与佣金（复用你已有逻辑）
    if USE_PG:
        cursor.execute("DELETE FROM bets WHERE code = %s", (code,))
        cursor.execute("DELETE FROM commissions WHERE code = %s", (code,))
    else:
        cursor.execute("DELETE FROM bets WHERE code = ?", (code,))
        cursor.execute("DELETE FROM commissions WHERE code = ?", (code,))
    conn.commit()

    await query.message.reply_text(f"✅ 已成功删除下注 Code: {code}")
    await query.answer()

async def cmd_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /commission
    显示最近 7 天（含今天）每天的下注总额与佣金总额。
    """
    # 计算起始日期（7 天前）
    start_date = date.today() - timedelta(days=6)

    if USE_PG:
        # Postgres：market 列是逗号分隔的市场字符串
        sql = """
        SELECT
          bet_date,
          SUM(array_length(string_to_array(market, ','), 1) * amount)::numeric AS total_amount,
          SUM(array_length(string_to_array(market, ','), 1) * commission)::numeric AS total_commission
        FROM bets
        WHERE bet_date >= %s
        GROUP BY bet_date
        ORDER BY bet_date DESC;
        """
        cursor.execute(sql, (start_date,))
    else:
        # SQLite：用 LENGTH 和 REPLACE 计算逗号数 + 1
        sql = """
        SELECT
          bet_date,
          SUM((LENGTH(market) - LENGTH(REPLACE(market, ',', '')) + 1) * amount) AS total_amount,
          SUM((LENGTH(market) - LENGTH(REPLACE(market, ',', '')) + 1) * commission) AS total_commission
        FROM bets
        WHERE date(bet_date) >= date('now', '-6 days')
        GROUP BY bet_date
        ORDER BY bet_date DESC;
        """
        cursor.execute(sql)

    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("最近 7 天内没有下注记录。")
        return

    # 格式化输出
    lines = []
    for bet_date, total_amt, total_com in rows:
        # bet_date 在 Postgres 下是 date 对象，在 SQLite 下可能是字符串
        if isinstance(bet_date, str):
            display_date = datetime.strptime(bet_date, "%Y-%m-%d").strftime("%d/%m")
        else:
            display_date = bet_date.strftime("%d/%m")
        lines.append(f"{display_date}：总额 RM{float(total_amt):.2f} / 佣金 RM{float(total_com):.2f}")

    await update.message.reply_text("\n".join(lines))

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /history
    列出最近 7 天按日期分组的所有下注明细，Markdown 格式输出。
    """
    # 1. 计算查询起始日期
    start_date = date.today() - timedelta(days=6)

    # 2. 拉取数据
    if USE_PG:
        sql = """
        SELECT bet_date, market, number, bet_type, mode,
               amount, potential_win, commission, code
          FROM bets
         WHERE bet_date >= %s
         ORDER BY bet_date DESC, created_at;
        """
        cursor.execute(sql, (start_date,))
    else:
        sql = """
        SELECT bet_date, market, number, bet_type, mode,
               amount, potential_win, commission, code
          FROM bets
         WHERE date(bet_date) >= date('now', '-6 days')
         ORDER BY bet_date DESC, created_at;
        """
        cursor.execute(sql)

    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("最近 7 天内没有下注记录。")
        return

    # 3. 分组整理
    grouped = defaultdict(list)
    for row in rows:
        bet_date, market, number, bet_type, mode, amount, potential, com, code = row
        # 统一格式化日期为 DD/MM
        if isinstance(bet_date, str):
            dt = datetime.strptime(bet_date, "%Y-%m-%d")
        else:
            dt = bet_date
        disp_date = dt.strftime("%d/%m")
        grouped[disp_date].append((market, number, bet_type, mode, amount, potential, com, code))

    # 4. 构造 Markdown 文本
    lines = []
    for disp_date in sorted(grouped.keys(), reverse=True):
        lines.append(f"*{disp_date}*")  # 日期标题
        for market, number, bet_type, mode, amount, potential, com, code in grouped[disp_date]:
            mode_txt = f" {mode.upper()}" if mode else ""
            lines.append(
                f"- `{market}`: `{number}-{amount}{bet_type}{mode_txt}`  │  "
                f"Win: RM{float(potential):.2f}  │  Com: RM{float(com):.2f}  │  `Code: {code}`"
            )
        lines.append("")  # 每个日期后留一空行

    text = "\n".join(lines).strip()
    await update.message.reply_text(text, parse_mode="Markdown")

def main():

    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error('BOT_TOKEN 未设置')
        return
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^任务$"), show_task_menu))
    app.add_handler(CallbackQueryHandler(handle_task_buttons, pattern=r"^task:"))
    app.add_handler( MessageHandler( filters.TEXT & ~filters.Regex(r'^/'), handle_bet_text)) 
    app.add_handler(CallbackQueryHandler(handle_confirm_bet, pattern="^confirm_bet$"))
    app.add_handler(CommandHandler('delete', cmd_delete))
    app.add_handler(CommandHandler('commission', cmd_commission))
    app.add_handler(CommandHandler('history', cmd_history))
    app.add_handler(CallbackQueryHandler(handle_delete_code, pattern="^delete_code:"))
    
    app.run_polling()

if __name__ == '__main__':
    main()
