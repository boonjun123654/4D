#!/usr/bin/env python3
import os
import logging
import random
import string
import threading
from telegram import CallbackQuery
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
from db import (
    conn, cursor,
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

async def handle_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 历史记录", callback_data="task:history")],
        [InlineKeyboardButton("💰 佣金报表", callback_data="task:commission")],
        [InlineKeyboardButton("🗑️ 删除下注", callback_data="task:delete")]
    ])
    await update.message.reply_text("📌 请选择任务操作：", reply_markup=keyboard)

PAGE_SIZE = 5
async def handle_task_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    group_id = str(query.message.chat.id)
    logger.info(f"👉 任务按钮触发！user_id: {user_id}, group_id: {group_id}, data: {query.data}")

    await query.answer()

    if data == "task:history":
        # 初始化頁面為第0頁
        context.user_data["history_page"] = 0
        await show_bet_history_page(query, context, user_id, group_id)

    elif data == "task:commission":
        today = datetime.now().date()
        start_date = today - timedelta(days=6)
        rows = get_commission_summary(user_id, start_date, today, group_id)

        if not rows:
            await query.message.reply_text("⚠️ 没有找到最近7天的佣金记录。")
            return

        lines = ["📊 佣金报表 (最近7天)\n"]
        for row in rows:
            lines.append(f"{row['day']}：总额 RM{row['total_amount']:.2f} / 佣金 RM{row['total_commission']:.2f}")
        await query.message.reply_text("\n".join(lines))

    elif data == "task:delete":
        recent_codes = get_recent_bet_codes(user_id, limit=5, group_id=group_id)
        if not recent_codes:
            await query.message.reply_text("⚠️ 你最近沒有下注記錄。")
            return

        keyboard = [
            [InlineKeyboardButton(f"❌ 刪除 {code}", callback_data=f"delete_code:{code}")]
            for code in recent_codes
        ]
        await query.message.reply_text("請選擇要刪除的下注 Code：", reply_markup=InlineKeyboardMarkup(keyboard))

elif data.startswith("history_page:"):
    page = int(data.split(":", 1)[1])
    context.user_data["history_page"] = page
    await show_bet_history_page(query, context, user_id, group_id)

elif data.startswith("delete_code:"):
    code = data.split(":", 1)[1]
    success = delete_bet_and_commission(code)
    if success:
        await query.message.reply_text(f"✅ 已成功删除下注 Code: {code}")
    else:
        await query.message.reply_text(f"⚠️ 删除失败，Code 不存在或已删除。")


    elif data.startswith("history_page:"):
        # 處理上一頁/下一頁點擊
        page = int(data.split(":")[1])
        context.user_data["history_page"] = page
        await show_bet_history_page(query, context, user_id, group_id)

    elif data.startswith("delete_code:"):
        code = data.split(":")[1]
        success = delete_bet_and_commission(code)
        if success:
            await query.message.reply_text(f"✅ 已成功刪除下注 Code: {code}")
        else:
            await query.message.reply_text(f"⚠️ 刪除失敗，該 code 不存在或已刪除。")

async def show_bet_history_page(callback_query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: str):
    per_page = 5
    page = context.user_data.get("history_page", 0)

    # 时间范围：最近7天
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)
    all_bets = get_bet_history(user_id, start_date, end_date, group_id)

    if not all_bets:
        await callback_query.edit_message_text("❗️你在最近 7 天没有下注记录。")
        return

    offset = page * per_page
    current = all_bets[offset: offset + per_page]

    text = "📜 <b>下注记录（最近7天）</b>\n\n"
    for b in current:
        text += (
            f"📅 {b['date']}\n"
            f"🔢 Code：<code>{b['code']}</code>\n"
            f"🎯 内容：{b['content']}\n"
            f"💸 金额：RM{b['amount']:.2f}\n"
            "----------------------\n"
        )

    # 分页按钮
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"history_page:{page-1}"))
    if offset + per_page < len(all_bets):
        buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"history_page:{page+1}"))

    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    await callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

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
    app.add_handler( MessageHandler( filters.TEXT & ~filters.Regex(r'^/'), handle_bet_text)) 
    app.add_handler(CallbackQueryHandler(handle_confirm_bet, pattern="^confirm_bet$"))
    app.add_handler(CallbackQueryHandler(handle_task_buttons, pattern="^task:|^history_page:|^delete_code:|^commission:"))
    app.add_handler(CommandHandler("task", handle_task_menu))

    app.run_polling()

if __name__ == '__main__':
    main()
