# -*- coding: utf-8 -*-
import sqlite3
import logging
import asyncio
import os
import threading
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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
    'a': 'Ａ', 'b': 'Ｂ', 'c': 'Ｃ', 'd': 'Ｄ', 'e': 'Ｅ', 'f': 'Ｆ', 'g': 'Ｇ', 'h': 'Ｈ', 'i': 'Ｉ', 'j': 'Ｊ',
    'k': 'Ｋ', 'l': 'Ｌ', 'm': 'Ｍ', 'n': 'Ｎ', 'o': 'Ｏ', 'p': 'Ｐ', 'q': 'Ｑ', 'r': 'Ｒ', 's': 'Ｓ', 't': 'Ｔ',
    'u': 'Ｕ', 'v': 'Ｖ', 'w': 'Ｗ', 'x': 'Ｘ', 'y': 'Ｙ', 'z': 'Ｚ',
    'A': 'Ａ', 'B': 'Ｂ', 'C': 'Ｃ', 'D': 'Ｄ', 'E': 'Ｅ', 'F': 'Ｆ', 'G': 'Ｇ', 'H': 'Ｈ', 'I': 'Ｉ', 'J': 'Ｊ',
    'K': 'Ｋ', 'L': 'Ｌ', 'M': 'Ｍ', 'N': 'Ｎ', 'O': 'Ｏ', 'P': 'Ｐ', 'Q': 'Ｑ', 'R': 'Ｒ', 'S': 'Ｓ', 'T': 'Ｔ',
    'U': 'Ｕ', 'V': 'Ｖ', 'W': 'Ｗ', 'X': 'Ｘ', 'Y': 'Ｙ', 'Z': 'Ｚ'
}
def f_txt(text): return "".join(FONT_MAP.get(c, c) for c in text)
def p_style(text): return f"<code>{text}</code>,"

# ================== DATABASE ==================
DB_PATH = "promo_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, joined INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, link TEXT, channel_id TEXT, name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS methods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, content TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, channel_name TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
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

# ================== FASTAPI ==================
web_app = FastAPI()

@web_app.get("/")
def read_root():
    return {"status": "Alive"}

def run_web():
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

# ================== KEYBOARDS ==================
user_states = {}

def get_join_keyboard():
    channels = db_exec("SELECT name, link FROM channels")
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(f"Join {ch[0]}", url=ch[1], style="primary")]) # Blue
    kb.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_membership", style="success")]) # Green
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
            try: await context.bot.send_message(admin, f"🆕 <b>NEW USER JOINED</b>\nID: <code>{user_id}</code>\nUsername: @{username}", parse_mode="HTML")
            except: pass

    channels = db_exec("SELECT * FROM channels")
    if channels:
        await update.message.reply_text(
            f"🔒 <b>{f_txt('CHANNEL SUBSCRIPTION REQUIRED')}</b>\n\n"
            f"You must join the following channels to use this bot:\n\n"
            f"After joining, tap the button below to verify.",
            reply_markup=get_join_keyboard(),
            parse_mode="HTML"
        )
    else:
        # Agar koi channel add nahi hai, toh direct methods send karo
        await send_methods_to_user(update, context)

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    channels = db_exec("SELECT channel_id, name FROM channels")
    not_joined = []
    
    for ch_id, ch_name in channels:
        try:
            # Format ID correctly
            chat_id = int(ch_id) if ch_id.lstrip('-').isdigit() else ch_id
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch_name)
        except Exception as e:
            # Agar bot admin nahi hai, toh error aayega
            logger.error(f"Check failed for {ch_name}: {e}")
            not_joined.append(f"{ch_name} (Bot is not Admin!)")
            
    if not_joined:
        return await query.message.reply_text(
            f"❌ You have not joined or verified: {', '.join(not_joined)}\n\n"
            f"Make sure you joined all channels. If this is a bot issue, tell admin.", 
            reply_markup=get_join_keyboard()
        )
        
    db_exec("UPDATE users SET joined=1 WHERE user_id=?", (user_id,))
    await query.message.reply_text(f"✅ <b>{f_txt('VERIFICATION SUCCESSFUL')}</b>\nHere are your methods:", parse_mode="HTML")
    
    # Automatically send methods after verification
    await send_methods_to_user(update, context, is_callback=True)

async def send_methods_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    methods = db_exec("SELECT type, content FROM methods")
    if not methods:
        msg = "❌ No methods available yet. Please wait!"
        if is_callback: await update.callback_query.message.reply_text(msg)
        else: await update.message.reply_text(msg)
        return
        
    for m_type, content in methods:
        try:
            if m_type == 'video':
                if is_callback: await update.callback_query.message.reply_video(video=content, caption="🎥 Method Video")
                else: await update.message.reply_video(video=content, caption="🎥 Method Video")
            elif m_type == 'text':
                if is_callback: await update.callback_query.message.reply_text(f"📝 <b>Method:</b>\n\n{content}", parse_mode="HTML")
                else: await update.message.reply_text(f"📝 <b>Method:</b>\n\n{content}", parse_mode="HTML")
        except: pass

# ================== OWNER PANEL ==================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in get_all_admins(): return
    
    kb = [
        [InlineKeyboardButton("➕ Add Channel", callback_data="admin_add_ch", style="primary"), InlineKeyboardButton("➖ Remove Channel", callback_data="admin_rem_ch", style="danger")],
        [InlineKeyboardButton("📊 Check All Members", callback_data="admin_members", style="success"), InlineKeyboardButton("🎥 Add Video Method", callback_data="admin_add_vid", style="primary")],
        [InlineKeyboardButton("👑 Add Admin", callback_data="admin_add", style="primary")]
    ]
    await update.message.reply_text(f"<b>👑 {f_txt('OWNER PANEL')}</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    
    if uid not in get_all_admins(): return await query.answer("Unauthorized", show_alert=True)
    
    if data == "admin_add_ch":
        await query.edit_message_text("🔗 Send Channel Link, ID, and Name separated by comma.\n\n<b>Format:</b>\n<code>https://t.me/yourchannel, -1001234567890, My Channel</code>", parse_mode="HTML")
        user_states[uid] = 'add_channel'
        
    elif data == "admin_add_vid":
        await query.edit_message_text("🎥 Please send the Video now:")
        user_states[uid] = 'waiting_video'
        
    elif data == "admin_rem_ch":
        channels = db_exec("SELECT id, name FROM channels")
        if not channels: return await query.edit_message_text("❌ No channels added.")
        kb = []
        for ch_id, name in channels:
            kb.append([InlineKeyboardButton(f"❌ Delete {name}", callback_data=f"delch_{ch_id}", style="danger")])
        await query.edit_message_text("Select channel to delete:", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data.startswith("delch_"):
        ch_id = int(data.split("_")[1])
        db_exec("DELETE FROM channels WHERE id=?", (ch_id,))
        await query.edit_message_text("✅ Channel removed.")
        
    elif data == "admin_members":
        users = db_exec("SELECT user_id, username FROM users")
        text = f"👥 <b>Total Members: {len(users)}</b>\n\n"
        for u in users[:20]:
            text += f"🆔 <code>{u[0]}</code> | @{u[1]}\n"
        if len(users) > 20: text += f"... and {len(users)-20} more."
        await query.edit_message_text(text, parse_mode="HTML")
        
    elif data == "admin_add":
        await query.edit_message_text("👑 Send User ID to make Admin:")
        user_states[uid] = 'add_admin'

async def admin_state_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = user_states.get(uid)
    
    if uid not in get_all_admins(): return
    
    if state == 'add_channel':
        try:
            parts = [p.strip() for p in text.split(",")]
            link, ch_id, name = parts[0], parts[1], parts[2]
            db_exec("INSERT INTO channels (link, channel_id, name) VALUES (?,?,?)", (link, ch_id, name))
            await update.message.reply_text(f"✅ {p_style('Channel Added')}", parse_mode="HTML")
        except:
            await update.message.reply_text("❌ Invalid format. Use: link, id, name")
        user_states[uid] = None
        
    elif state == 'add_admin':
        if text.isdigit():
            db_exec("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(text),))
            await update.message.reply_text(f"✅ {p_style('Admin Added')}", parse_mode="HTML")
        user_states[uid] = None

async def save_method_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if user_states.get(uid) == 'waiting_video' and update.message.video:
        file_id = update.message.video.file_id
        db_exec("INSERT INTO methods (type, content) VALUES (?,?)", ('video', file_id))
        await update.message.reply_text("✅ Video Method Saved!")
        user_states[uid] = None

async def save_method_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_admins(): return
    text = update.message.text.replace("/savemethod", "").strip()
    if text:
        db_exec("INSERT INTO methods (type, content) VALUES (?,?)", ('text', text))
        await update.message.reply_text("✅ Text Method Saved!")

# ================== MAIN ==================
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("owner", owner_panel))
    app_bot.add_handler(CommandHandler("savemethod", save_method_text))
    
    app_bot.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    app_bot.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^(admin_|delch_)"))
    
    app_bot.add_handler(MessageHandler(filters.VIDEO, save_method_video))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_state_router))

    logger.info("Promo Bot started successfully.")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
