import os
import sys
import re
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    TELEGRAM_BOT_TOKEN,
    GEMINI_API_KEY,
    ORIGIN_ADDRESS,
    RATE_PER_KM,
    RECEIPTS_DIR,
    AUTHORIZED_USER_ID
)
from database import (
    init_db,
    add_car_trip,
    add_transit_trip,
    get_month_trips,
    delete_last_trip,
    save_chat_id,
    get_registered_chat_ids
)
from distance_calculator import calculate_distance_with_ai_fallback
from receipt_parser import parse_transit_receipt
from report_generator import generate_monthly_report
from google import genai
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class CarTripExtracted(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    destination: str = Field(description="Destination address or place name")
    explicit_km: float = Field(default=0.0, description="Explicit distance in KM if stated by the user, otherwise 0")

def parse_car_text_with_gemini(text: str) -> CarTripExtracted:
    """Extracts date and destination from user's free text message."""
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    
    # 1. Try Gemini if API key is provided
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""
היום הוא {today_str}.
המשתמש כתב הודעה על נסיעה ברכב. חלץ:
1. תאריך הנסיעה בפורמט YYYY-MM-DD (אם כתב "אתמול", "שלשום", "היום" או תאריך ספציפי - חשב את התאריך המדויק. ברירת מחדל: {today_str}).
2. יעד הנסיעה (שם המקום / כתובת היעד).
3. אם המשתמש ציין במפורש קילומטראז' (למשל "15 קמ"), חלץ אותו כמספר עשרוני. אם לא ציין, החזר 0.

טקסט המשתמש: "{text}"
"""
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=dict(
                    response_mime_type="application/json",
                    response_schema=CarTripExtracted
                )
            )
            if response.text:
                import json
                data = json.loads(response.text)
                return CarTripExtracted(**data)
        except Exception as e:
            logger.error(f"Error parsing car text with Gemini: {e}")
            
    # 2. Smart regex & Hebrew fallback
    extracted_date = today_str
    extracted_km = 0.0
    dest = text

    # Check relative dates
    if "אתמול" in text:
        extracted_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        dest = dest.replace("אתמול", "")
    elif "שלשום" in text:
        extracted_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        dest = dest.replace("שלשום", "")
    elif "היום" in text:
        dest = dest.replace("היום", "")

    # Check explicit date (DD/MM/YYYY or DD/MM or DD.MM.YYYY or DD.MM)
    date_match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", dest)
    if date_match:
        d = int(date_match.group(1))
        m = int(date_match.group(2))
        y = int(date_match.group(3)) if date_match.group(3) else today.year
        if y < 100:
            y += 2000
        try:
            extracted_date = f"{y:04d}-{m:02d}-{d:02d}"
            dest = dest.replace(date_match.group(0), "")
        except Exception:
            pass

    # Check explicit KM (e.g. 15.5 קמ / 20 ק"מ)
    km_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ק\"?מ|קילומטר|קילומטרים)\b", dest)
    if km_match:
        extracted_km = float(km_match.group(1))
        dest = dest.replace(km_match.group(0), "")

    # Clean destination text
    dest = re.sub(r"\b(נסעתי|נסיעה|הגעה|הייתי|פגישה|אל|ל)\b", " ", dest)
    dest = re.sub(r"\s+", " ", dest).strip(" ,:-")
    if not dest:
        dest = text

    return CarTripExtracted(date=extracted_date, destination=dest, explicit_km=extracted_km)

def is_authorized(user_id: int) -> bool:
    if not AUTHORIZED_USER_ID:
        return True
    return str(user_id) == str(AUTHORIZED_USER_ID)

def get_target_chat_ids() -> List[int]:
    """Returns list of target chat IDs to receive notifications."""
    if AUTHORIZED_USER_ID:
        return [int(AUTHORIZED_USER_ID)]
    return get_registered_chat_ids()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message and instructions."""
    user = update.effective_user
    chat = update.effective_chat
    save_chat_id(chat.id, user.username or "", user.first_name or "")

    welcome_text = (
        f"👋 שלום {user.first_name}!\n\n"
        f"אני האייג'נט האישי שלך לניהול והפקת **החזרי נסיעות חודשיים** 🚗 🚌\n\n"
        f"📍 **נקודת מוצא לרכב:** {ORIGIN_ADDRESS}\n"
        f"🔄 **חישוב מרחק ברכב:** תמיד כפול (הלוך וחזור מהבית)\n"
        f"💵 **תעריף לק\"מ:** {RATE_PER_KM:.2f} ₪\n\n"
        f"📌 **כיצד להשתמש?**\n"
        f"• **נסיעה ברכב:** שלח הודעת טקסט (למשל: `15/09 נסעתי לפגישה ברחובות`)\n"
        f"• **תחבורה ציבורית:** שלח צילום מסך של קבלה/היסטוריה (Moovit, רב-קו וכו')\n\n"
        f"📋 **פקודות שימושיות:**\n"
        f"• `/summary` - צפייה בסיכום החודש הנוכחי\n"
        f"• `/report` - הפקה והורדה מיידית של קובץ האקסל\n"
        f"• `/report 09` - הפקת דוח לחודש מסוים (למשל ספטמבר)\n"
        f"• `/undo` - מחיקת הרשומה האחרונה\n\n"
        f"⏰ **לוח זמנים אוטומטי:**\n"
        f"🔔 **ב-29 לכל חודש:** תזכורת ראשונה למילוי נסיעות החודש\n"
        f"🔔 **ב-1 לחודש הבא:** תזכורת שנייה לסגירת החודש שחלף\n"
        f"📄 **ב-3 לחודש הבא:** הפקה ושליחה אוטומטית של קובץ ה-Excel הסופי!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current month's totals."""
    if not is_authorized(update.effective_user.id):
        return

    now = datetime.now()
    data = get_month_trips(now.year, now.month)
    car_trips = data["car_trips"]
    transit_trips = data["transit_trips"]

    total_km = sum(t["distance_km"] for t in car_trips)
    total_car_cost = sum(t["cost"] for t in car_trips)
    total_transit_cost = sum(t["cost"] for t in transit_trips)
    grand_total = total_car_cost + total_transit_cost

    msg = (
        f"📊 **סיכום נסיעות לחודש {now.month:02d}/{now.year}:**\n\n"
        f"🚗 **נסיעות ברכב:** {len(car_trips)} נסיעות\n"
        f"  • סה\"כ מרחק: {total_km:.1f} ק\"מ\n"
        f"  • סה\"כ החזר רכב: {total_car_cost:.2f} ₪\n\n"
        f"🚌 **תחבורה ציבורית:** {len(transit_trips)} נסיעות\n"
        f"  • סה\"כ החזר תחב\"צ: {total_transit_cost:.2f} ₪\n\n"
        f"💰 **סה\"כ החזר חודשי מצטבר:** **{grand_total:.2f} ₪**\n\n"
        f"להורדת קובץ האקסל המעוצב שלח `/report`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates and sends the Excel report file."""
    if not is_authorized(update.effective_user.id):
        return

    now = datetime.now()
    # Check if a specific month/year was passed, e.g. /report 09 or /report 2026-09
    args = context.args
    year, month = now.year, now.month
    if args and len(args) > 0:
        arg_val = args[0]
        if "-" in arg_val:
            parts = arg_val.split("-")
            year, month = int(parts[0]), int(parts[1])
        elif arg_val.isdigit():
            month = int(arg_val)

    await update.message.reply_text(f"⏳ מפיק דוח אקסל מעוצב לחודש {month:02d}/{year}...")
    try:
        file_path = generate_monthly_report(year, month)
        with open(file_path, "rb") as doc:
            await update.message.reply_document(
                document=doc,
                filename=Path(file_path).name,
                caption=f"📄 **דוח החזרי נסיעות - חודש {month:02d}/{year}**\nהקובץ מוכן להגשה!",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        await update.message.reply_text(f"❌ שגיאה בהפקת הדוח: {e}")

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the last recorded trip."""
    if not is_authorized(update.effective_user.id):
        return
    
    trip = delete_last_trip("car") or delete_last_trip("transit")
    if trip:
        await update.message.reply_text("🗑️ הרשומה האחרונה נמחקה בהצלחה.")
    else:
        await update.message.reply_text("ℹ️ אין רשומות למחיקה.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages representing car trips."""
    if not is_authorized(update.effective_user.id):
        return

    chat = update.effective_chat
    user = update.effective_user
    save_chat_id(chat.id, user.username or "", user.first_name or "")

    text = update.message.text.strip()
    if not text:
        return

    wait_msg = await update.message.reply_text("🔍 מעבד נתוני נסיעה ומחשב מרחק...")

    extracted = parse_car_text_with_gemini(text)
    
    if extracted.explicit_km > 0:
        distance_km = round(extracted.explicit_km, 1)
        calc_note = "לפי קילומטראז' שצוין ידנית"
        dist_display = f"{distance_km} ק\"מ"
    else:
        one_way_km, calc_note = calculate_distance_with_ai_fallback(extracted.destination)
        distance_km = round(one_way_km * 2, 1)
        dist_display = f"{one_way_km} ק\"מ לכיוון (סה\"כ {distance_km} ק\"מ הלוך-חזור)"

    cost = round(distance_km * RATE_PER_KM, 2)
    
    # Save to database (saves round-trip km for the report)
    add_car_trip(
        date=extracted.date,
        destination=extracted.destination,
        distance_km=distance_km,
        rate_per_km=RATE_PER_KM,
        notes=calc_note
    )

    reply_text = (
        f"✅ **נרשמה נסיעה ברכב!**\n\n"
        f"📅 **תאריך:** `{extracted.date}`\n"
        f"📍 **יעד:** {extracted.destination}\n"
        f"📏 **מרחק מהבית:** {dist_display}\n"
        f"💵 **תעריף:** {RATE_PER_KM:.2f} ₪ לק\"מ\n"
        f"💰 **עלות נסיעה כוללת:** **{cost:.2f} ₪**\n"
        f"ℹ️ _{calc_note}_\n\n"
        f"לביטול: `/undo` | לדוח: `/report`"
    )
    await wait_msg.edit_text(reply_text, parse_mode="Markdown")

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles screenshot uploads for transit expenses."""
    if not is_authorized(update.effective_user.id):
        return

    chat = update.effective_chat
    user = update.effective_user
    save_chat_id(chat.id, user.username or "", user.first_name or "")

    wait_msg = await update.message.reply_text("🔍 מפעיל ראייה ממוחשבת לפענוח הקבלה...")

    photo = update.message.photo[-1]  # Highest resolution
    file = await photo.get_file()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_image_path = RECEIPTS_DIR / f"receipt_{timestamp}.jpg"
    await file.download_to_drive(str(local_image_path))

    if not GEMINI_API_KEY:
        await wait_msg.edit_text(
            "⚠️ **נדרש מפתח Gemini API לפענוח תמונות:**\n"
            "כדי שהבוט יוכל לקרוא צילומי מסך ולפענח קבלות באופן אוטומטי, יש להגדיר מפתח Gemini API (חינמי) בקובץ `.env`.\n\n"
            "ניתן להפיק מפתח בחינם ב-Google AI Studio תוך 10 שניות.",
            parse_mode="Markdown"
        )
        return

    # Parse with Gemini Vision
    trips = parse_transit_receipt(str(local_image_path))
    
    if not trips:
        await wait_msg.edit_text("❌ לא הצלחתי לפענח את פרטי הנסיעה מהתמונה. נסה לשלוח צילום מסך ברור יותר או הזן את הנסיעה בטקסט.")
        return

    # Save all parsed trips to database
    total_added_cost = 0.0
    trip_lines = []
    for t in trips:
        add_transit_trip(
            date=t["date"],
            details=t["details"],
            cost=t["cost"],
            image_path=str(local_image_path)
        )
        total_added_cost += t["cost"]
        trip_lines.append(f"• `{t['date']}` | {t['details']} | **{t['cost']:.2f} ₪**")

    reply_text = (
        f"✅ **נרשמו בהצלחה {len(trips)} נסיעות תחב\"צ!**\n\n"
        + "\n".join(trip_lines) + "\n\n"
        f"💰 **סה\"כ שנוסף:** **{total_added_cost:.2f} ₪**\n\n"
        f"לצפייה בסיכום: `/summary` | להורדת אקסל: `/report`"
    )
    await wait_msg.edit_text(reply_text, parse_mode="Markdown")

async def send_reminder_day_29(app):
    """Fires on the 29th of every month at 09:00 - Reminder to submit current month's expenses."""
    now = datetime.now()
    chats = get_target_chat_ids()
    logger.info(f"Sending 29th monthly reminder for {now.month:02d}/{now.year} to {len(chats)} chats.")
    for chat_id in chats:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔔 **תזכורת נסיעות חודשית (29 ל-{now.month:02d})** 🚗 🚌\n\n"
                    f"סוף החודש מתקרב! זה הזמן לוודא שהזנת את כל נסיעות הרכב וצילומי המסך של תחב\"צ עבור חודש **{now.month:02d}/{now.year}**.\n\n"
                    f"📊 לצפייה בסיכום שנצבר עד כה: `/summary`\n"
                    f"📄 להפקת טיוטת אקסל: `/report`"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send 29th reminder to {chat_id}: {e}")

async def send_reminder_day_1(app):
    """Fires on the 1st of every month at 09:00 - Reminder to finalize last month's expenses."""
    now = datetime.now()
    first_day = now.replace(day=1)
    prev_month_date = first_day - timedelta(days=1)
    prev_month = prev_month_date.month
    prev_year = prev_month_date.year
    
    chats = get_target_chat_ids()
    logger.info(f"Sending 1st of month reminder for {prev_month:02d}/{prev_year} to {len(chats)} chats.")
    for chat_id in chats:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔔 **תזכורת לסגירת חודש (1 ל-{now.month:02d})** 📅\n\n"
                    f"חודש **{prev_month:02d}/{prev_year}** הסתיים אתמול.\n"
                    f"אנא ודא שהזנת את כל הנסיעות והקבלות שנותרו מהחודש שחלף.\n\n"
                    f"🚀 **שים לב:** ב-**3 לחודש** בשעה 09:00 אפיק ואשלח לך אוטומטית את קובץ ה-Excel הסופי והמלא!"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send 1st of month reminder to {chat_id}: {e}")

async def send_monthly_report_day_3(app):
    """Fires on the 3rd of every month at 09:00 - Automatically generates and sends the final report."""
    now = datetime.now()
    first_day = now.replace(day=1)
    prev_month_date = first_day - timedelta(days=1)
    prev_year = prev_month_date.year
    prev_month = prev_month_date.month

    logger.info(f"Generating and sending final report for {prev_month:02d}/{prev_year} on day 3.")
    
    file_path = generate_monthly_report(prev_year, prev_month)
    chats = get_target_chat_ids()
    for chat_id in chats:
        try:
            with open(file_path, "rb") as doc:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=doc,
                    filename=Path(file_path).name,
                    caption=(
                        f"📄 **דוח החזרי נסיעות חודשי סופי (3 ל-{now.month:02d})**\n\n"
                        f"מצורף קובץ האקסל המסכם עבור חודש **{prev_month:02d}/{prev_year}**.\n"
                        f"הקובץ מעוצב, מחושב ומוכן להגשה! 🚀"
                    ),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to send day 3 report to {chat_id}: {e}")

async def post_init(application):
    scheduler = AsyncIOScheduler()
    
    # 1. Day 29 at 09:00 - Reminder to fill expenses
    scheduler.add_job(
        send_reminder_day_29,
        CronTrigger(day=29, hour=9, minute=0),
        args=[application]
    )
    
    # 2. Day 1 at 09:00 - Reminder for finalized past month
    scheduler.add_job(
        send_reminder_day_1,
        CronTrigger(day=1, hour=9, minute=0),
        args=[application]
    )
    
    # 3. Day 3 at 09:00 - Final automated monthly Excel report delivery
    scheduler.add_job(
        send_monthly_report_day_3,
        CronTrigger(day=3, hour=9, minute=0),
        args=[application]
    )
    
    scheduler.start()
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to satisfy Render web service port and UptimeRobot keep-alive pings."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK - Travel Expense Bot is running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Silence console access logs from keep-alive pings
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Keep-Alive HTTP server listening on 0.0.0.0:{port}")
    server.serve_forever()

def main():
    init_db()
    
    # Start Keep-Alive HTTP server on separate daemon thread (for Render and UptimeRobot)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN is not set in .env file.")
        print("Please configure your TELEGRAM_BOT_TOKEN in .env and restart.")
        return

    t_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(t_request).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("undo", undo_command))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    print("🤖 Travel Expense Agent Telegram Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
