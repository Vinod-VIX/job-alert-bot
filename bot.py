import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from sheet_utils import read_sheet_rows, remove_expired_rows
import config

from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------- config shortcuts ----------------
BOT_TOKEN = config.BOT_TOKEN
DATE_FORMATS = config.DATE_FORMATS
OUTPUT_DATE_FORMAT = getattr(config, "OUTPUT_DATE_FORMAT", "%d/%m/%Y")
RESEND_ALL_ON_NEW = config.RESEND_ALL_ON_NEW
SENT_JOBS_FILE = config.SENT_JOBS_FILE
SUBSCRIBERS_FILE = config.SUBSCRIBERS_FILE
DEFAULT_SUBSTITUTION = getattr(config, "DEFAULT_SUBSTITUTION", "Refer official ad")

MESSAGE_IDS_FILE = "message_ids.json"
PREMIUM_FILE = "premium_users.json"

ADMIN_ID = config.ADMIN_ID
CHECK_INTERVAL_MINUTES = int(os.getenv("JOB_INTERVAL_MINUTES", "60"))

# Telegram max limit
MAX_LEN = 4000

# ---------------- UPI config ----------------
UPI_ID = config.UPI_ID   # e.g. "vinod@okaxis"

# ---------------- JSON helpers ----------------
def load_json_file(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json_file(path: str, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_premium_users() -> dict:
    return load_json_file(PREMIUM_FILE, {})

def save_premium_users(users: dict):
    save_json_file(PREMIUM_FILE, users)

# ---------------- utility ----------------
def parse_indian_date(s: str):
    if not s:
        return None
    s = str(s).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        return datetime.strptime(s, "%d %b %Y").date()
    except Exception:
        return None

def build_job_id(title: str, last_date: str) -> str:
    return f"{title.strip().lower()}|{last_date.strip()}"

# ---------------- formatting ----------------
def format_job_text(row: Dict[str, str]) -> str:
    ld = parse_indian_date(row.get("Last Date", ""))
    date_text = ld.strftime(OUTPUT_DATE_FORMAT) if ld else row.get("Last Date", "")
    title = row.get("Job Title", "Untitled Job")
    age = row.get("Age Limit", "") or DEFAULT_SUBSTITUTION
    qual = row.get("Qualification", "") or DEFAULT_SUBSTITUTION
    exp = row.get("Experience", "") or DEFAULT_SUBSTITUTION
    apply_link = row.get("Apply Link", "").strip()

    message = (
        f"🔔 <b>{title}</b>\n"
        f"🗓 <b>Last Date:</b> {date_text}\n"
        f"🎯 <b>Age Limit:</b> {age}\n"
        f"🎓 <b>Qualification:</b> {qual}\n"
        f"💼 <b>Experience:</b> {exp}"
    )
    if apply_link:
        message += f"\n🔗 <a href='{apply_link}'>Apply Here</a>"
    return message

# ---------------- footer keyboard ----------------
def build_footer_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Share this bot", url="https://t.me/IndiaJobBot65_bot")],
        [InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="subscribe")]
    ])

def premium_teaser_text() -> str:
    return (
        "ℹ️ <b>You are on Free Plan</b>\n\n"
        "👉 Use /start to get the latest job details (limited list).\n"
        "👉 Use /resendall to re-check jobs (limits apply).\n\n"
        "🔒 Want ALL jobs without limits?\n"
        "👉 Use /subscribe to unlock Premium!"
    )
    
def split_messages(source: str, rows: List[Dict[str, str]]) -> List[str]:
    job_blocks = [format_job_text(r) for r in rows]
    messages = []
    current_chunk = f"📌 <b>{source}</b>\n\n"
    for job in job_blocks:
        if len(current_chunk) + len(job) + 2 > MAX_LEN:
            messages.append(current_chunk.strip())
            current_chunk = job + "\n\n"
        else:
            current_chunk += job + "\n\n"
    if current_chunk.strip():
        messages.append(current_chunk.strip())
    return messages

# ---------------- sending ----------------
async def send_or_edit_group_message(bot: Bot, chat_id: int, source: str, rows: List[Dict[str,str]], message_ids: dict, is_premium: bool):
    chat_key = str(chat_id)
    if chat_key not in message_ids:
        message_ids[chat_key] = {}

    if not is_premium:
        rows = rows[:2]

    messages = split_messages(source, rows)

    if len(messages) > 1:
        for msg in messages:
            try:
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=build_footer_keyboard())
            except Exception as e:
                logger.warning("Send failed to %s: %s", chat_id, e)
        return

    text = messages[0]
    if source in message_ids[chat_key]:
        mid = message_ids[chat_key][source]
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=mid, text=text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=build_footer_keyboard())
            return
        except Exception as e:
            logger.warning("Edit failed for chat=%s source=%s: %s", chat_id, source, e)

    try:
        msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=build_footer_keyboard())
        message_ids[chat_key][source] = msg.message_id
        save_json_file(MESSAGE_IDS_FILE, message_ids)
    except Exception as e:
        logger.warning("Send failed to %s: %s", chat_id, e)

# ---------------- job checker ----------------
async def check_jobs(bot: Bot):
    logger.info("Running job check...")

    sent_jobs = load_json_file(SENT_JOBS_FILE, [])
    sent_set = set(sent_jobs)

    raw_rows = read_sheet_rows()
    rows = remove_expired_rows(raw_rows)
    active_rows = [r for _, r in rows]

    if not active_rows:
        save_json_file(SENT_JOBS_FILE, [])
        save_json_file(MESSAGE_IDS_FILE, {})
        logger.info("No active jobs left.")
        return

    job_ids = [build_job_id(r.get("Job Title",""), r.get("Last Date","")) for r in active_rows]
    sent_jobs = [jid for jid in sent_jobs if jid in job_ids]
    sent_set = set(sent_jobs)

    subscribers = load_json_file(SUBSCRIBERS_FILE, [])
    if not subscribers:
        return

    grouped = defaultdict(list)
    for jid, r in zip(job_ids, active_rows):
        grouped[r.get("Source", "General")].append((jid, r))

    message_ids = load_json_file(MESSAGE_IDS_FILE, {})

    for chat in subscribers:
        chat_id = int(chat)
        is_premium = is_premium_user(chat_id)
        for source, jid_rows in grouped.items():
            rows_to_send = [r for _, r in jid_rows]
            jids_in_source = [jid for jid, _ in jid_rows]

            new_in_source = [jid for jid in jids_in_source if jid not in sent_set]
            if new_in_source:
                await send_or_edit_group_message(bot, chat_id, source, rows_to_send, message_ids, is_premium)
                for jid in new_in_source:
                    sent_jobs.append(jid)
                    sent_set.add(jid)

        if not is_premium:
            try:
                await bot.send_message(chat_id=chat_id, text=premium_teaser_text(), parse_mode="HTML")
            except Exception:
                pass

    save_json_file(SENT_JOBS_FILE, sent_jobs)
    save_json_file(MESSAGE_IDS_FILE, message_ids)

# ---------------- commands ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = load_json_file(SUBSCRIBERS_FILE, [])
    if chat_id not in subs:
        subs.append(chat_id)
        save_json_file(SUBSCRIBERS_FILE, subs)
        await update.message.reply_text(f"✅ Subscribed to job updates.\nYour Chat ID: {chat_id}")
    else:
        await update.message.reply_text(f"ℹ️ Already subscribed.\nYour Chat ID: {chat_id}")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = load_json_file(SUBSCRIBERS_FILE, [])
    if chat_id in subs:
        subs.remove(chat_id)
        save_json_file(SUBSCRIBERS_FILE, subs)
        await update.message.reply_text("❌ Unsubscribed.")
    else:
        await update.message.reply_text("ℹ️ Not subscribed.")

async def cmd_resendall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = read_sheet_rows()
    rows = remove_expired_rows(rows)
    active_rows = [r for _, r in rows]
    if not active_rows:
        await update.message.reply_text("No active jobs.")
        save_json_file(SENT_JOBS_FILE, [])
        save_json_file(MESSAGE_IDS_FILE, {})
        return

    grouped = defaultdict(list)
    for r in active_rows:
        grouped[r.get("Source","General")].append(r)

    message_ids = load_json_file(MESSAGE_IDS_FILE, {})
    job_ids = [build_job_id(r.get("Job Title",""), r.get("Last Date","")) for r in active_rows]
    save_json_file(SENT_JOBS_FILE, job_ids)

    chat_id = update.effective_chat.id
    is_premium = is_premium_user(chat_id)
    for source, rs in grouped.items():
        await send_or_edit_group_message(context.bot, chat_id, source, rs, message_ids, is_premium)

    save_json_file(MESSAGE_IDS_FILE, message_ids)

    if not is_premium:
        await context.bot.send_message(chat_id=chat_id, text=premium_teaser_text(), parse_mode="HTML")
        
    import qrcode
    from io import BytesIO

# ---------------- UPI Subscribe ----------------
from io import BytesIO
import qrcode

async def generate_upi_qr(upi_id: str, amount: int, note: str = "Job Bot Premium"):
    """Generate a QR code image for UPI payment."""
    upi_link = f"upi://pay?pa={upi_id}&pn=Vinod%20Kumar&am={amount}&cu=INR&tn={note}"
    qr = qrcode.make(upi_link)
    bio = BytesIO()
    bio.name = "upi_qr.png"
    qr.save(bio, "PNG")
    bio.seek(0)
    return bio

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    amount = 199

    text = (
        "🔒 <b>Upgrade to Premium</b>\n\n"
        f"💰 Amount: ₹{amount} (one-time)\n\n"
        "👉 Pay using any UPI app:\n"
        f"📌 <b>UPI ID:</b> <code>{UPI_ID}</code>\n\n"
        "📷 Or simply scan the QR code below to pay instantly.\n\n"
        "After payment, please upload a screenshot here 📸\n"
        "Admin will verify & activate your Premium ✅"
    )

    # Send the instructions text
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML"
    )

    # Send the QR code
    qr_image = await generate_upi_qr(UPI_ID, amount)
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=qr_image,
        caption=f"📷 Scan & Pay ₹{amount} to {UPI_ID}"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "copy_upi":
        await query.message.reply_text(f"📌 UPI ID: <code>{UPI_ID}</code>", parse_mode="HTML")
    elif query.data == "subscribe":
        # Trigger your existing cmd_subscribe logic
        await cmd_subscribe(update, context)

# ---------------- Screenshot auto-forward ----------------
async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    caption = (
        f"📸 Payment screenshot received!\n\n"
        f"👤 From: {user.full_name} (@{user.username})\n"
        f"🆔 Chat ID: {chat_id}\n\n"
        f"👉 Use /addpremium {chat_id} to approve."
    )

    try:
        file_id = update.message.photo[-1].file_id
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=caption)
        await update.message.reply_text("📩 Screenshot received! Waiting for admin approval ⏳")
    except Exception as e:
        await update.message.reply_text("⚠️ Could not forward screenshot to admin.")
        logger.error(f"Screenshot forward failed: {e}")

# ---------------- Premium admin ----------------
async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        target_id = str(int(context.args[0]))
    except:
        await update.message.reply_text("Usage: /addpremium <chat_id>")
        return

    users = load_premium_users()
    expiry = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
    users[target_id] = expiry
    save_premium_users(users)

    # ✅ Also auto-add to subscribers.json
    subs = load_json_file(SUBSCRIBERS_FILE, [])
    if target_id not in subs:
        subs.append(target_id)
        save_json_file(SUBSCRIBERS_FILE, subs)

    await update.message.reply_text(f"✅ {target_id} added as Premium until {expiry}")
    try:
        # ✅ Notify user directly
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"🌟 Congratulations! You are now a Premium user until {expiry} 🚀\n"
                 f"You will now automatically receive all job updates."
        )
    except Exception as e:
        logger.warning(f"Could not notify user {target_id}: {e}")
        
async def cmd_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        target_id = str(int(context.args[0]))
    except:
        await update.message.reply_text("Usage: /removepremium <chat_id>")
        return

    users = load_premium_users()
    if target_id in users:
        del users[target_id]
        save_premium_users(users)

        # 🔻 Also remove from subscribers.json
        subs = load_json_file(SUBSCRIBERS_FILE, [])
        if target_id in subs:
            subs.remove(target_id)
            save_json_file(SUBSCRIBERS_FILE, subs)

        await update.message.reply_text(f"❌ {target_id} removed from Premium and unsubscribed.")
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text="⚠️ Your Premium subscription has been revoked. You will no longer receive job updates."
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id}: {e}")
    else:
        await update.message.reply_text(f"User {target_id} is not in Premium list.")

# ---------------- Premium status ----------------
async def cmd_premiumstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    users = load_premium_users()
    subs = load_json_file(SUBSCRIBERS_FILE, [])

    if user_id in users:
        await update.message.reply_text(
            "✅ You are a Premium user. You will continue receiving unrestricted job updates."
        )
    elif user_id in subs:
        await update.message.reply_text(
            "ℹ️ You are a Free user. You will get limited job alerts.\n\n"
            "👉 Use /subscribe to upgrade and unlock all job alerts."
        )
    else:
        await update.message.reply_text(
            "⚠️ You are not subscribed.\n\n"
            "👉 Use /subscribe to start receiving job alerts."
        )

# --------------------- broadcast message --------------------
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow admin
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not allowed to use this command.")
        return

    # Combine arguments to form the broadcast message
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    subs = load_json_file(SUBSCRIBERS_FILE, [])
    for chat_id in subs:
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to send to {chat_id}: {e}")

    await update.message.reply_text(f"✅ Broadcast sent to {len(subs)} subscriber(s).")


# ---------------- check premium ----------------
def is_premium_user(chat_id: int) -> bool:
    users = load_premium_users()
    exp = users.get(str(chat_id))
    if not exp:
        return False
    try:
        expiry_date = datetime.strptime(exp, "%Y-%m-%d").date()
        return expiry_date >= datetime.utcnow().date()
    except:
        return False
        
# ---------------- Minimal HTTP server for Render ----------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write("✅ Bot is running on Render!".encode("utf-8"))

def run_http_server():
    port = int(os.environ.get("PORT", 10000))  # Render sets $PORT
    server = HTTPServer(("", port), SimpleHandler)
    print(f"HTTP server running on port {port}", flush=True)
    server.serve_forever()

# ---------------- main ----------------
def main():
    if "--once" in sys.argv:
        bot = Bot(token=BOT_TOKEN)
        asyncio.run(check_jobs(bot))
    else:
        # start HTTP server in background (for Render)
        threading.Thread(target=run_http_server, daemon=True).start()

        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("resendall", cmd_resendall))
        app.add_handler(CommandHandler("subscribe", cmd_subscribe))
        app.add_handler(CommandHandler("addpremium", cmd_addpremium))
        app.add_handler(CommandHandler("removepremium", cmd_removepremium))
        app.add_handler(CommandHandler("premiumstatus", cmd_premiumstatus))
        app.add_handler(CommandHandler("broadcast", cmd_broadcast))

        app.add_handler(CallbackQueryHandler(button_handler))

        # ✅ Screenshot handler
        app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))

        app.job_queue.run_repeating(
            lambda ctx: asyncio.create_task(check_jobs(ctx.bot)),
            interval=CHECK_INTERVAL_MINUTES * 60,
            first=10,
        )

        app.run_polling()

if __name__ == "__main__":
    main()
