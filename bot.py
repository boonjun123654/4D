
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from db import (
    save_bets, delete_user_bets, get_win_records, calculate_commission,
    get_user_bets, get_all_commissions, get_max_win_amount
)
from parser import parse_bet_message

OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
AGENT_IDS = [int(x) for x in os.getenv("AGENT_IDS", "").split(",") if x]
temp_bets = {}

def is_owner(user_id):
    return user_id == OWNER_ID

def is_agent(user_id):
    return user_id in AGENT_IDS

def get_main_menu(user_id):
    if is_owner(user_id):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ 写字", callback_data="write")],
            [InlineKeyboardButton("📜 查看历史", callback_data="history")],
            [InlineKeyboardButton("🧾 删除下注记录", callback_data="delete")],
            [InlineKeyboardButton("🎯 查看中奖记录", callback_data="check_wins")],
            [InlineKeyboardButton("📊 财务", callback_data="finance")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ 写字", callback_data="write")],
            [InlineKeyboardButton("📜 查看历史", callback_data="history")],
            [InlineKeyboardButton("🧾 删除下注记录", callback_data="delete")],
            [InlineKeyboardButton("🎯 查看中奖记录", callback_data="check_wins")],
            [InlineKeyboardButton("💰 佣金", callback_data="commission")],
        ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("欢迎使用4D下注系统，请选择操作：", reply_markup=get_main_menu(update.effective_user.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "write":
        await query.message.reply_text("请输入下注内容：\n格式示例：\n07/06/2025\nMKT\n1234-1B 1S ibox")
    elif query.data == "delete":
        delete_user_bets(user_id)
        await query.message.reply_text("✅ 你的下注记录已全部删除")
    elif query.data == "check_wins":
        records = get_win_records(user_id, all_user=is_owner(user_id))
        await query.message.reply_text(records or "暂无中奖记录")
    elif query.data == "commission":
        amt = calculate_commission(user_id)
        await query.message.reply_text(f"💰 你的佣金累计：RM{amt:.2f}")
    elif query.data == "finance":
        summary = get_all_commissions()
        await query.message.reply_text(summary or "暂无佣金记录")
    elif query.data == "confirm_bet":
        user_id = query.from_user.id
        if user_id in temp_bets:
            save_bets(user_id, temp_bets[user_id])
            await query.message.edit_text("✅ 下注成功！", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("继续下注", callback_data="write")],
                [InlineKeyboardButton("查看历史", callback_data="history")]
            ]))
            del temp_bets[user_id]
        else:
            await query.message.edit_text("❌ 没有待确认的下注")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (is_owner(user_id) or is_agent(user_id)):
        await update.message.reply_text("你无权限使用本Bot。")
        return

    text = update.message.text
    try:
        bets = parse_bet_message(text)
        temp_bets[user_id] = bets
        total_amount = sum(b["amount"] for b in bets)
        max_win = get_max_win_amount(bets)

        bet_summary = "\n".join([f'{b["market"]} {b["number"]}-{b["amount"]}{b["bet_type"]} {b["box_type"] or ""}' for b in bets])
        await update.message.reply_text(
            f"请确认以下下注内容：\n\n{bet_summary}\n\n总下注：RM{total_amount:.2f}\n最大可赢：RM{max_win:.2f}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 确认下注", callback_data="confirm_bet")]])
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ 无法识别下注格式，请确认后再试。\n正确格式示例：\n07/06/2025\nMKT\n1234-1B 1S ibox\n\n错误详情：{e}"
        )

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

app.run_polling()
