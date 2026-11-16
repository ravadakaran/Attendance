
import os
import re
import asyncio
import sqlite3
import logging

from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler


# ---------------- CONFIGURATION ----------------

load_dotenv()

PORTAL_URL = "https://internmo.com/projects/login"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USERNAME = os.getenv("INTERNMO_USER")
PASSWORD = os.getenv("INTERNMO_PASSWORD")

TIMEZONE = ZoneInfo(
    os.getenv("TIMEZONE", "Asia/Kolkata")
)

CHECK_HOUR = int(os.getenv("CHECK_HOUR", "8"))
CHECK_MINUTE = int(os.getenv("CHECK_MINUTE", "0"))

DB_NAME = os.getenv("DB_PATH", "attendance.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)


# ---------------- DATABASE ----------------

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                status TEXT,
                checked_at TEXT
            )
        """)


def save_history(status):
    now = datetime.now(TIMEZONE)

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO attendance
            (date, status, checked_at)
            VALUES (?, ?, ?)
        """, (
            now.strftime("%Y-%m-%d"),
            status,
            now.strftime("%H:%M:%S")
        ))


def get_history():
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("""
            SELECT date, status, checked_at
            FROM attendance
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()


# ---------------- INTERNMO CHECK ----------------

def check_internmo():

    if not USERNAME or not PASSWORD:
        return "ERROR: Missing Internmo credentials."

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 900})

        try:
            logger.info("Opening Internmo")

            page.goto(
                PORTAL_URL,
                wait_until="domcontentloaded",
                timeout=45000
            )

            # Login
            page.get_by_placeholder(
                "you@example.com or PMIN1001"
            ).fill(USERNAME)

            page.locator(
                "input[type='password']"
            ).fill(PASSWORD)

            page.get_by_role(
                "button",
                name="Sign in",
                exact=True
            ).click()

            page.wait_for_url(
                "**/projects/user**",
                timeout=30000
            )

            page.wait_for_timeout(2000)

            # Check if Mark Present button is directly on dashboard or attendance page
            mark_button = page.get_by_role(
                "button",
                name=re.compile(r"^(?:mark\s+)?present$", re.IGNORECASE)
            )

            if mark_button.count() >= 1 and mark_button.first.is_visible():
                logger.info("Found Mark Present button on dashboard. Clicking it...")
                mark_button.first.click()
                page.wait_for_timeout(3000)

            # Open attendance page
            page.get_by_text(
                "Attendance",
                exact=True
            ).first.click()

            page.wait_for_timeout(2500)

            # Check if Mark Present button is on the attendance page
            attendance_mark_button = page.get_by_role(
                "button",
                name=re.compile(r"^(?:mark\s+)?present$", re.IGNORECASE)
            )

            if attendance_mark_button.count() >= 1 and attendance_mark_button.first.is_visible():
                logger.info("Found Mark Present button on Attendance page. Clicking it...")
                attendance_mark_button.first.click()
                page.wait_for_timeout(3000)

            page_text = page.locator("body").inner_text()
            upper_text = page_text.upper()

            logger.info("Attendance page inspected")

            if (
                "PRESENT TODAY" in upper_text
                or "MARKED PRESENT FOR TODAY" in upper_text
                or "PRESENT" in upper_text
            ):
                return "PRESENT"

            return "NOT_CONFIRMED"

        except Exception as error:
            logger.exception("Internmo check failed")
            return "ERROR: " + str(error)[:300]

        finally:
            browser.close()


# ---------------- TELEGRAM SECURITY ----------------

def authorized(update: Update):

    return (
        update.effective_chat is not None
        and CHAT_ID is not None
        and str(update.effective_chat.id) == str(CHAT_ID)
    )


# ---------------- CHECK ATTENDANCE ----------------

async def perform_check(application):

    chat_id = int(CHAT_ID)

    await application.bot.send_message(
        chat_id=chat_id,
        text="🔍 Checking your Internmo attendance..."
    )

    result = await asyncio.to_thread(check_internmo)

    now = datetime.now(TIMEZONE)

    if result == "PRESENT":

        save_history("PRESENT")

        message = (
            "✅ INTERNMO ATTENDANCE\n\n"
            "Status: PRESENT\n"
            f"Date: {now.strftime('%d-%m-%Y')}\n"
            f"Checked at: {now.strftime('%I:%M %p')}\n\n"
            "Your attendance is already recorded."
        )

    elif result == "NOT_CONFIRMED":

        save_history("NOT_CONFIRMED")

        message = (
            "⚠️ ATTENDANCE NOT CONFIRMED\n\n"
            f"Date: {now.strftime('%d-%m-%Y')}\n\n"
            "I could not find confirmation that "
            "today's attendance is recorded.\n\n"
            "Please open Internmo, verify that you "
            "are present, and complete the permitted "
            "check-in action yourself."
        )

    else:

        save_history("ERROR")

        message = (
            "❌ INTERNMO CHECK FAILED\n\n"
            f"Details: {result}\n\n"
            "Please inspect the portal manually."
        )

    await application.bot.send_message(
        chat_id=chat_id,
        text=message
    )


# ---------------- TELEGRAM COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    await update.message.reply_text(
        "👋 Welcome to Internmo Attendance Assistant!\n\n"
        "Your bot is connected.\n\n"
        "Commands:\n"
        "/status - Check attendance\n"
        "/check - Run attendance check\n"
        "/history - View attendance history\n"
        "/schedule - View daily schedule\n"
        "/help - Show commands"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    await update.message.reply_text(
        "🔍 Checking your attendance..."
    )

    result = await asyncio.to_thread(check_internmo)

    save_history(result)

    await update.message.reply_text(
        "Attendance result: " + result
    )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    await update.message.reply_text(
        "Starting attendance check..."
    )

    await perform_check(context.application)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    records = get_history()

    if not records:

        await update.message.reply_text(
            "No attendance history available yet."
        )

        return

    message = "📊 ATTENDANCE CHECK HISTORY\n\n"

    for date, result, time in records:

        message += (
            f"📅 {date}\n"
            f"Status: {result}\n"
            f"Time: {time}\n\n"
        )

    await update.message.reply_text(message)


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    await update.message.reply_text(
        "⏰ Daily attendance check\n\n"
        "Time: 8:00 AM\n"
        "Timezone: Asia/Kolkata\n"
        "Frequency: Every day"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not authorized(update):
        return

    await update.message.reply_text(
        "/start - Start bot\n"
        "/status - Check attendance\n"
        "/check - Run a new check\n"
        "/history - Attendance history\n"
        "/schedule - Daily schedule\n"
        "/help - Help"
    )


# ---------------- SCHEDULER ----------------

async def daily_check(application):

    try:

        logger.info("Starting scheduled attendance check")

        await perform_check(application)

    except Exception:

        logger.exception("Scheduled check failed")


# ---------------- MAIN ----------------

async def post_init(application):

    scheduler = AsyncIOScheduler(
        timezone=TIMEZONE
    )

    scheduler.add_job(
        daily_check,
        trigger="cron",
        hour=CHECK_HOUR,
        minute=CHECK_MINUTE,
        args=[application],
        id="daily_attendance_check",
        replace_existing=True,
        max_instances=1
    )

    scheduler.start()

    application.bot_data["scheduler"] = scheduler

    logger.info(
        "Daily schedule enabled: %02d:%02d",
        CHECK_HOUR,
        CHECK_MINUTE
    )


async def post_shutdown(application):

    scheduler = application.bot_data.get("scheduler")

    if scheduler:
        scheduler.shutdown(wait=False)


def main():

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing Telegram bot token or chat ID."
        )

    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "Missing Internmo login credentials."
        )

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("help", help_command))

    logger.info("Internmo Telegram bot started")

    app.run_polling()


if __name__ == "__main__":
    main()
