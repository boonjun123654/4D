#!/usr/bin/env python3
import os
import logging
import random
import string
import threading
from db import USE_PG
from db import init_db
init_db()
from collections import OrderedDict
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
        return


async def show_delete_code_page(query, context, group_id):
    # 获取所有下注 code
    all_codes = get_recent_bet_codes(group_id=group_id)
    unique_codes = list(dict.fromkeys(all_codes))  # 保持顺序去重
    total_codes = len(unique_codes)

    page = context.user_data.get("delete_page", 0)
    logger.info(f"调用分页函数，当前页码：{page}")

    offset = page * PAGE_SIZE
    current_codes = unique_codes[offset: offset + PAGE_SIZE]

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
        buttons.append(InlineKeyboardButton("⬅ 上一页", callback_data=f"delete_page:{page-1}"))
    if offset + PAGE_SIZE < total_codes:
        buttons.append(InlineKeyboardButton("➡ 下一页", callback_data=f"delete_page:{page+1}"))
    if buttons:
        keyboard.append(buttons)

    # 发送消息
    await query.message.edit_text(
        f"🗑 请选择要删除的下注 Code：\n\n📄 正在显示第 {page + 1} 页 / 共 {(total_codes + PAGE_SIZE - 1) // PAGE_SIZE} 页",
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
        if USE_PG:
            c.execute(
                "DELETE FROM bets WHERE code=%s AND group_id=%s",
                (code, group_id)
            )
        else:
            c.execute(
                "DELETE FROM bets WHERE code=? AND group_id=?",
                (code, group_id)
            )
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
    app.add_handler( MessageHandler( filters.TEXT & ~filters.Regex(r'^/'), handle_bet_text)) 
    app.add_handler(CallbackQueryHandler(handle_confirm_bet, pattern="^confirm_bet$"))
    app.add_handler(CallbackQueryHandler(handle_task_buttons, pattern="^task:|^history_day:|^delete_code:|^confirm_delete:|^commission:|^delete_page:"))
    app.add_handler(CommandHandler("task", handle_task_menu))

    app.run_polling()

if __name__ == '__main__':
    main()
