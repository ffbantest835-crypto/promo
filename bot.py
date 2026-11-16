# -*- coding: utf-8 -*-
import sqlite3
import logging
import asyncio
import os
import threading
import qrcode
from io import BytesIO
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9083925993:AAE9ikMA5FfkfUz7bsjNWWOOW65YE0tH8Q0")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== STYLISH FONTS ==================
FONT_MAP = {
    'a': 'ａ', 'b': 'ｂ', 'c': 'ｃ', 'd': 'ｄ', 'e': 'ｅ', 'f': 'ｆ', 'g': 'ｇ', 'h': 'ｈ', 'i': 'ｉ', 'j': 'ｊ',
    'k': 'ｋ', 'l': 'ｌ', 'm': 'ｍ', 'n': 'ｎ', 'o': 'ｏ', 'p': 'ｐ', 'q': 'ｑ', 'r': 'ｒ', 's': 'ｓ', 't': 'ｔ',
    'u': 'ｕ', 'v': 'ｖ', 'w': 'ｗ', 'x': 'ｘ', 'y': 'ｙ', 'z': 'ｚ',
    'A': 'Ａ', 'B': 'Ｂ', 'C': 'Ｃ', 'D': 'Ｄ', 'E': 'Ｅ', 'F': 'Ｆ', 'G': 'Ｇ', 'H': 'Ｈ', 'I': 'Ｉ', 'J': 'Ｊ',
    'K': 'Ｋ', 'L': 'Ｌ', 'M': 'Ｍ', 'N': 'Ｎ', 'O': 'Ｏ', 'P': 'Ｐ', 'Q': 'Ｑ', 'R': 'Ｒ', 'S': 'Ｓ', 'T': 'Ｔ',
    'U': 'Ｕ', 'V': 'Ｖ', 'W': 'Ｗ', 'X': 'Ｘ', 'Y': 'Ｙ', 'Z': 'Ｚ'
}
def f_txt(text): return "".join(FONT_MAP.get(c, c) for c in text)
def p_style(text): return f"<code>{text}</code>,"

# ================== DATABASE ==================
DB_PATH = "paid_promo_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, joined INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, link TEXT, channel_id TEXT, name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, plan TEXT, screenshot TEXT, status TEXT DEFAULT 'Pending'
    )""")
    conn.commit()
    conn.close()

init_db()

def db_exec(query, params=()):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    try:
        c.execute(query, params)
        conn.commit()
        res = c.fetchall()
    finally:
        conn.close()
    return res

def get_all_admins():
    res = db_exec("SELECT user_id FROM admins")
    return [row[0] for row in res] if res else []

def get_config(key, default=None):
    res = db_exec("SELECT value FROM config WHERE key=?", (key,))
    return res[0][0] if res else default

def set_config(key, value):
    db_exec("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", (key, value))

# ================== FASTAPI ==================
web_app = FastAPI()

@web_app.get("/")
def read_root(): return {"status": "Alive"}

def run_web():
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

# ================== KEYBOARDS & STATE ==================
user_states = {}

def get_join_keyboard():
    channels = db_exec("SELECT name, link FROM channels")
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(f"Join {ch[0]}", url=ch[1], style="primary")])
    kb.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_membership", style="success")])
    return InlineKeyboardMarkup(kb)

def get_plan_keyboard():
    kb = [
        [InlineKeyboardButton("15.64 Rs MONTH", callback_data="plan_15", style="primary")],
        [InlineKeyboardButton("17.89 Rs MONTH", callback_data="plan_17", style="primary")],
        [InlineKeyboardButton("👑 PERMANENT 25Rs 👑", callback_data="plan_25", style="primary")]
    ]
    return InlineKeyboardMarkup(kb)

def get_qr_keyboard():
    kb = [
        [InlineKeyboardButton("✅ I Have Paid", callback_data="paid", style="primary"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_pay", style="danger")]
    ]
    return InlineKeyboardMarkup(kb)

def get_approve_keyboard(user_id, req_id):
    kb = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{req_id}", style="success"), InlineKeyboardButton("❌ Disapprove", callback_data=f"disapprove_{user_id}_{req_id}", style="danger")]
    ]
    return InlineKeyboardMarkup(kb)

# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "No Username"
    
    total_admins = db_exec("SELECT COUNT(*) FROM admins")[0][0]
    if total_admins == 0:
        db_exec("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))

    res = db_exec("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not res:
        db_exec("INSERT INTO users (user_id, username) VALUES (?,?)", (user_id, username))
        for admin in get_all_admins():
            try: await context.bot.send_message(admin, f"🆕 <b>NEW USER</b>\nID: <code>{user_id}</code>\n@{username}", parse_mode="HTML")
            except: pass

    # WELCOME MESSAGE
    welcome_text = f"👋 <b>{f_txt('WELCOME TO PAID POMPOM BOT')}</b>\n\nPlease join the group to continue:"
    
    welcome_photo = get_config("welcome_photo")
    welcome_video = get_config("welcome_video")

    if welcome_video:
        await update.message.reply_video(video=welcome_video, caption=welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")
    elif welcome_photo:
        await update.message.reply_photo(photo=welcome_photo, caption=welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(welcome_text, reply_markup=get_join_keyboard(), parse_mode="HTML")

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # BYPASS: Jo bhi button dabaye, seedha verify ho jayega (no check)
    db_exec("UPDATE users SET joined=1 WHERE user_id=?", (user_id,))
    
    # Price List
    plan_text = (
        f"💦 <b>{f_txt('WELCOME TO POOM GROUP')}</b> 💦\n\n"
        f"💰 <b>{f_txt('PRICE LIST')}</b> 💰\n\n"
        f"➊ .. 15.64 Rs MONTH\n"
        f"➎ .. 17.89 Rs MONTH\n\n"
        f"👑 <b>PERMANENT .. 25Rs</b> 👑"
    )
    
    plan_photo = get_config("plan_photo")
    if plan_photo:
        await query.message.reply_photo(photo=plan_photo, caption=plan_text, reply_markup=get_plan_keyboard(), parse_mode="HTML")
    else:
        await query.message.reply_text(plan_text, reply_markup=get_plan_keyboard(), parse_mode="HTML")

async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = query.data.split("_")[1]
    context.user_data['plan'] = plan
    
    upi_id = get_config("upi_id")
    if not upi_id:
        return await query.message.reply_text("❌ Admin has not set UPI ID yet. Please contact admin.")

    amount = "15.64" if plan == "15" else "17.89" if plan == "17" else "25"
    upi_url = f"upi://pay?pa={upi_id}&pn=Payment&am={amount}&cu=INR"
    
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = BytesIO()
    bio.name = 'qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    qr_caption = f"📸 <b>{f_txt('SCAN TO PAY')}</b>\n\nAmount: <b>{amount} Rs</b>\nUPI: <code>{upi_id}</code>"
    await query.message.reply_photo(photo=InputFile(bio, 'qr.png'), caption=qr_caption, reply_markup=get_qr_keyboard(), parse_mode="HTML")

async def qr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_pay":
        await query.message.delete()
        return
        
    if query.data == "paid":
        context.user_data['waiting_screenshot'] = True
        await query.message.reply_text("📸 Please send your Payment Screenshot now.")

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_screenshot'): return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or "No Username"
    photo = update.message.photo[-1].file_id
    plan = context.user_data.get('plan', 'Unknown')
    
    db_exec("INSERT INTO requests (user_id, username, plan, screenshot) VALUES (?,?,?,?)", (user_id, username, plan, photo))
    req_id = db_exec("SELECT last_insert_rowid()")[0][0]
    
    context.user_data['waiting_screenshot'] = False
    await update.message.reply_text("⏳ Screenshot sent for verification. Please wait for approval.")
    
    admin_text = f"🔔 <b>NEW PAYMENT PROOF</b>\n\nUser: @{username} (<code>{user_id}</code>)\nPlan: {plan} Rs"
    for admin in get_all_admins():
        try: await context.bot.send_photo(admin, photo=photo, caption=admin_text, reply_markup=get_approve_keyboard(user_id, req_id), parse_mode="HTML")
        except Exception as e: logger.error(f"Failed to send to admin {admin}: {e}")

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    action, user_id, req_id = data[0], int(data[1]), int(data[2])
    
    if action == "approve":
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ <b>APPROVED by Admin</b>", parse_mode="HTML")
        db_exec("UPDATE requests SET status='Approved' WHERE id=?", (req_id,))
        await context.bot.send_message(user_id, "🎉 <b>Payment Approved!</b>\n\nYour access has been granted.")
    elif action == "disapprove":
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ <b>REJECTED by Admin</b>", parse_mode="HTML")
        db_exec("UPDATE requests SET status='Rejected' WHERE id=?", (req_id,))
        await context.bot.send_message(user_id, "❌ Payment was rejected. Please contact admin.")

# ================== OWNER PANEL ==================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in get_all_admins(): return
    
    kb = [
        [InlineKeyboardButton("➕ Add Group", callback_data="admin_add_ch", style="primary"), InlineKeyboardButton("➖ Remove Group", callback_data="admin_rem_ch", style="danger")],
        [InlineKeyboardButton("💳 Set UPI ID", callback_data="admin_set_upi", style="primary"), InlineKeyboardButton("🖼 Set Welcome Pic", callback_data="admin_set_welcome", style="primary")],
        [InlineKeyboardButton("🎬 Set Welcome Vid", callback_data="admin_set_wvid", style="primary"), InlineKeyboardButton("🖼 Set Plan Pic", callback_data="admin_set_planpic", style="primary")],
        [InlineKeyboardButton("📊 Total Users", callback_data="admin_members", style="success"), InlineKeyboardButton("👑 Add Admin", callback_data="admin_add", style="primary")]
    ]
    await update.message.reply_text(f"<b>👑 {f_txt('OWNER PANEL')}</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    
    if uid not in get_all_admins(): return await query.answer("Unauthorized", show_alert=True)
    
    if data == "admin_add_ch":
        await query.edit_message_text("🔗 Send Group Link, ID, and Name separated by comma.\n<code>https://t.me/test, -1001234567890, My Group</code>", parse_mode="HTML")
        user_states[uid] = 'add_channel'
    elif data == "admin_set_upi":
        await query.edit_message_text("💳 Send your UPI ID (e.g. name@upi):")
        user_states[uid] = 'set_upi'
    elif data == "admin_set_welcome":
        await query.edit_message_text("🖼 Send the Welcome Photo:")
        user_states[uid] = 'set_welcome'
    elif data == "admin_set_wvid":
        await query.edit_message_text("🎬 Send the Welcome Video:")
        user_states[uid] = 'set_wvid'
    elif data == "admin_set_planpic":
        await query.edit_message_text("🖼 Send the 2nd Photo (For Price List):")
        user_states[uid] = 'set_planpic'
    elif data == "admin_rem_ch":
        channels = db_exec("SELECT id, name FROM channels")
        if not channels: return await query.edit_message_text("❌ No channels added.")
        kb = [[InlineKeyboardButton(f"❌ Delete {name}", callback_data=f"delch_{ch_id}", style="danger")] for ch_id, name in channels]
        await query.edit_message_text("Select channel to delete:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("delch_"):
        db_exec("DELETE FROM channels WHERE id=?", (int(data.split("_")[1]),))
        await query.edit_message_text("✅ Channel removed.")
    elif data == "admin_members":
        users = db_exec("SELECT user_id, username FROM users")
        text = f"👥 <b>Total Users: {len(users)}</b>\n\n"
        for u in users[:20]: text += f"🆔 <code>{u[0]}</code> | @{u[1]}\n"
        await query.edit_message_text(text, parse_mode="HTML")
    elif data == "admin_add":
        await query.edit_message_text("👑 Send User ID to make Admin:")
        user_states[uid] = 'add_admin'

async def admin_state_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text if update.message.text else ""
    state = user_states.get(uid)
    
    if uid not in get_all_admins(): return
    
    if state == 'add_channel':
        try:
            parts = [p.strip() for p in text.split(",")]
            db_exec("INSERT INTO channels (link, channel_id, name) VALUES (?,?,?)", (parts[0], parts[1], parts[2]))
            await update.message.reply_text(f"✅ {p_style('Group Added')}", parse_mode="HTML")
        except: await update.message.reply_text("❌ Invalid format.")
        user_states[uid] = None
        
    elif state == 'set_upi':
        set_config("upi_id", text)
        await update.message.reply_text(f"✅ {p_style('UPI ID Set')}", parse_mode="HTML")
        user_states[uid] = None
        
    elif state == 'add_admin':
        if text.isdigit():
            db_exec("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(text),))
            await update.message.reply_text(f"✅ {p_style('Admin Added')}", parse_mode="HTML")
        user_states[uid] = None

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_states.get(uid)
    
    if state == 'set_welcome' and update.message.photo:
        set_config("welcome_photo", update.message.photo[-1].file_id)
        await update.message.reply_text("✅ Welcome Photo Saved!")
        user_states[uid] = None
    elif state == 'set_planpic' and update.message.photo:
        set_config("plan_photo", update.message.photo[-1].file_id)
        await update.message.reply_text("✅ Plan Photo Saved!")
        user_states[uid] = None
    else:
        await handle_screenshot(update, context)

async def handle_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if user_states.get(uid) == 'set_wvid' and update.message.video:
        set_config("welcome_video", update.message.video.file_id)
        await update.message.reply_text("✅ Welcome Video Saved!")
        user_states[uid] = None

# ================== MAIN ==================
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("owner", owner_panel))
    
    app_bot.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    app_bot.add_handler(CallbackQueryHandler(plan_selected, pattern="^plan_"))
    app_bot.add_handler(CallbackQueryHandler(qr_callback, pattern="^(paid|cancel_pay)$"))
    app_bot.add_handler(CallbackQueryHandler(approve_callback, pattern="^(approve|disapprove)_"))
    app_bot.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^(admin_|delch_)"))
    
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photos))
    app_bot.add_handler(MessageHandler(filters.VIDEO, handle_videos))
    
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_state_router))

    logger.info("Paid Promo Bot started successfully.")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
