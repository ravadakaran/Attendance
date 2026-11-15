"""
Standalone script to run attendance check and send Telegram notification.
Used directly by GitHub Actions or local cron.
"""
import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Bot
from bot import check_internmo, init_db, save_history

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kolkata"))

async def notify():
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    bot = Bot(token=BOT_TOKEN)
    chat_id = int(CHAT_ID)
    now = datetime.now(TIMEZONE)

    print("Checking Internmo attendance...")
    result = await asyncio.to_thread(check_internmo)
    print(f"Result: {result}")

    try:
        init_db()
    except Exception as e:
        print(f"Database init warning: {e}")

    if result == "PRESENT":
        try:
            save_history("PRESENT")
        except Exception:
            pass
        message = (
            "✅ INTERNMO ATTENDANCE\n\n"
            "Status: PRESENT\n"
            f"Date: {now.strftime('%d-%m-%Y')}\n"
            f"Checked at: {now.strftime('%I:%M %p')}\n\n"
            "Your attendance is already recorded."
        )
    elif result == "NOT_CONFIRMED":
        try:
            save_history("NOT_CONFIRMED")
        except Exception:
            pass
        message = (
            "⚠️ ATTENDANCE NOT CONFIRMED\n\n"
            f"Date: {now.strftime('%d-%m-%Y')}\n\n"
            "I could not find confirmation that today's attendance is recorded.\n\n"
            "Please open Internmo and complete your attendance check-in."
        )
    else:
        try:
            save_history("ERROR")
        except Exception:
            pass
        message = (
            "❌ INTERNMO CHECK FAILED\n\n"
            f"Details: {result}\n\n"
            "Please inspect the portal manually."
        )

    await bot.send_message(chat_id=chat_id, text=message)
    print("Telegram notification sent successfully!")

if __name__ == "__main__":
    asyncio.run(notify())

