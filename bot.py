import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from dotenv import load_dotenv
from db import save_bets, get_bet_history, calculate_commission, get_all_commissions, delete_bets, get_win_history, get_max_win_amount, save_win_numbers
from parser import parse_bet_input

temp_bets = {}

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

MAIN_MENU_AGENT = [["✍️ 写字", "📜 查看历史"], ["🧾 删除记录", "💵 佣金"], ["🎯 查看中奖"]]
MAIN_MENU_OWNER = [["✍️ 写字", "📜 查看历史"], ["🧾 删除记录", "📊 财务"], ["🎯 查看中奖"]]

temp_bets = {}

def is_owner(uid):
    return uid == OWNER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_owner(user_id):
        menu = MAIN_MENU_OWNER
    else:
        menu = MAIN_MENU_AGENT
    await update.message.reply_text(
        "欢迎使用 4D Telegram Bot，请选择操作：",
        reply_markup=ReplyKeyboardMarkup(menu, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    uid = user.id
    uname = user.username or ""

    if text == "📜 查看历史":
        rows = get_bet_history(uid)
        if not rows:
            await update.message.reply_text("暂无下注记录。")
        else:
            msg = "📋 下注记录：\n"
            for r in rows:
                msg += f"{r[0]} | {r[1]} | {r[2]}-{r[3]} {r[4]} RM{r[5]}\n"
            await update.message.reply_text(msg)
        return

    if text == "💵 佣金":
        total = calculate_commission(uid)
        await update.message.reply_text(f"你的累计佣金为：RM{total:.2f}")
        return

    if text == "📊 财务" and is_owner(uid):
        all_data = get_all_commissions()
        msg = "📊 代理佣金分布：\n"
        for username, total in all_data:
            msg += f"@{username or '未知'}：RM{total:.2f}\n"
        await update.message.reply_text(msg)
        return

    if text == "🧾 删除记录":
        from db import delete_bets
        deleted = delete_bets(uid)
        await update.message.reply_text(f"✅ 已删除 {deleted} 条下注记录。")
        return


    if text == "🎯 查看中奖":
        wins = get_win_history(uid)
        if not wins:
            await update.message.reply_text("尚无中奖记录。")
        else:
            msg = "🎉 中奖记录：\n"
            for r in wins:
                msg += f"{r[0]} | {r[1]}-{r[2]} {r[3]} RM{r[4]}\n"
            await update.message.reply_text(msg)
        return

    if not any(x in text for x in ['B', 'S', 'A', 'C']):
        await update.message.reply_text("❌ 无效格式，请输入如：\nMKT 1234-1B 1S\n支持多日下注格式：\n07/06/2025&08/06/2025 MKT 1234-1B")
        return

    try:
        bets = parse_bet_input(text, uid, uname)
        temp_bets[uid] = bets

        # 计算最高可能中奖金额
        from parser import get_max_win_amount
        max_win = get_max_win_amount(bets)

        keyboard = [
            [InlineKeyboardButton("✅ 确认下注", callback_data="confirm_bet")],
        ]
        await update.message.reply_text(
            f"✅ 共 {len(bets)} 条记录，最高可赢 RM{max_win:.2f}，请点击确认下注：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 格式错误：{e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "confirm_bet":
        if user_id not in temp_bets:
            await query.edit_message_text("❌ 无可确认的下注记录。请重新发送格式。")
            return
        save_bets(user_id, temp_bets[user_id])
        del temp_bets[user_id]
        await query.edit_message_text("✅ 成功记录下注！")

async def set_win_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ 只有老板可设置开奖号码")
        return

    text = update.message.text.replace("/开奖号码", "").strip()
    if not text:
        await update.message.reply_text("请提供开奖号码，格式示例：\n/开奖号码 1234,2234,...")
        return

    try:
        numbers = [n.strip() for n in text.split(",") if n.strip()]
        msg = save_win_numbers(numbers)
        await update.message.reply_text(msg or "✅ 开奖号已保存并完成中奖计算")
    except Exception as e:
        await update.message.reply_text(f"❌ 设置失败：{e}")

async def confirm_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    await query.answer()

    if user_id not in temp_bets:
        await query.edit_message_text("❗未找到待确认的下注记录，请重新输入。")
        return

    bets = temp_bets[user_id]

    # 保存下注
    save_bets(user_id, username, bets)

    # 计算总额和最大可能中奖金额
    total = sum(b['amount'] for b in bets)
    max_win = get_max_win_amount(bets)

    # 删除临时缓存
    del temp_bets[user_id]

    await query.edit_message_text(
        f"✅下注成功！\n\n📌 共下注：{len(bets)}笔\n🧾 总金额：RM{total:.2f}\n🎯 最高可能中奖：RM{max_win:.2f}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 再下一笔", callback_data="write_bet")],
            [InlineKeyboardButton("📖 查看历史", callback_data="view_history")]
        ])
    )



if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setwin", set_win_numbers))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(confirm_bet, pattern="^confirm_bet$"))

    app.run_polling()
