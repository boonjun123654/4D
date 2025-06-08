#!/usr/bin/env python3
import os
import logging
import random
import string
from datetime import datetime
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
    await query.answer(text="下注处理中…", show_alert=False)

    bets = context.user_data.get('pending_bets')
    if not bets:
        await query.answer(text="⚠️ 未找到待确认的下注记录，请重新下注！", show_alert=True)
        return



    # 生成删除 Code
    date_str = datetime.now().strftime('%y%m%d')
    rand_letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    delete_code = f"{date_str}{rand_letters}"

    # 批量写库
    for bet in bets:
        params = (
            query.from_user.id,
            bet['date'],
            ','.join(bet['markets']),  # 记录所有市场
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
                "INSERT INTO bets (agent_id,bet_date,market,number,bet_type,mode,amount,potential_win,commission,code)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
        else:
            sql = (
                "INSERT INTO bets (agent_id,bet_date,market,number,bet_type,mode,amount,potential_win,commission,code)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)"
            )
        cursor.execute(sql, params)
    conn.commit()

    # 清除按钮，发送成功提示
    await query.edit_message_text(
        f"✅ 下注成功！\nCode：{delete_code}\n如需删除，请使用：/delete {delete_code}"
    )

    context.user_data.pop('pending_bets', None)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("请提供删除 Code，例如：/delete 250608ABC")
        return
    code = args[0]
    # 查询并删除
    if USE_PG:
        cursor.execute("SELECT COUNT(*) FROM bets WHERE code = %s", (code,))
    else:
        cursor.execute("SELECT COUNT(*) FROM bets WHERE code = ?", (code,))
    count = cursor.fetchone()[0]
    if not count:
        await update.message.reply_text("⚠️ 未找到该 Code 对应的下注记录。")
        return
    if USE_PG:
        cursor.execute("DELETE FROM bets WHERE code = %s", (code,))
    else:
        cursor.execute("DELETE FROM bets WHERE code = ?", (code,))
    conn.commit()
    await update.message.reply_text("✅ 下注记录已删除。")

async def cmd_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # TODO: 实现过去7天的报表查询
    await update.message.reply_text("功能待完善：/commission 报表")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # TODO: 实现过去7天的详细记录查询
    await update.message.reply_text("功能待完善：/history 报表")


def main():
    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error('BOT_TOKEN 未设置')
        return
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bet_text))
    app.add_handler(CallbackQueryHandler(handle_confirm_bet, pattern="^confirm_bet$"))
    app.add_handler(CommandHandler('delete', cmd_delete))
    app.add_handler(CommandHandler('commission', cmd_commission))
    app.add_handler(CommandHandler('history', cmd_history))

    app.run_polling()

if __name__ == '__main__':
    main()
