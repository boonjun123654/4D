import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from parser import parse_bet_text
from db import save_bets, get_bet_history, calculate_commission, get_all_commissions

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

# 菜单键盘
def get_menu(user_id):
    if user_id == OWNER_ID:
        return ReplyKeyboardMarkup([["✍️ 写字"], ["📜 查看历史"], ["📊 财务"]], resize_keyboard=True)
    return ReplyKeyboardMarkup([["✍️ 写字"], ["📜 查看历史"], ["💵 佣金"]], resize_keyboard=True)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("欢迎使用 4D Bot，请选择操作：", reply_markup=get_menu(update.effective_user.id))

# 接收文字
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    if text == "✍️ 写字":
        await update.message.reply_text("请输入下注格式：\n07/06/2025\nMKT\n1234-2B 1S ibox")
        return

    elif text == "📜 查看历史":
        records = get_bet_history(user.id)
        if not records:
            await update.message.reply_text("暂无下注记录")
            return
        msg = "\n".join([f"{d} [{m}] {n}-{t} {a}" for d, m, n, t, a in records])
        await update.message.reply_text(f"最近记录：\n{msg}")
        return

    elif text == "💵 佣金":
        c = calculate_commission(user.id)
        await update.message.reply_text(f"你目前累计佣金：RM {c:.2f}")
        return

    elif text == "📊 财务" and user.id == OWNER_ID:
        rows = get_all_commissions()
        msg = "\n".join([f"{u}: RM {c:.2f}" for u, c in rows]) or "暂无佣金数据"
        await update.message.reply_text(f"代理佣金总览：\n{msg}")
        return

    # 否则解析下注
    parsed = parse_bet_text(text)
    if parsed:
        save_bets(user.id, user.username or "无名", parsed)
        await update.message.reply_text(f"✅ 成功记录 {len(parsed)} 条下注")
    else:
        await update.message.reply_text("❌ 无法解析下注格式，请检查格式是否正确。")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
