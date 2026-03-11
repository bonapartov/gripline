from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

TOKEN = "8757289839:AAFQBEL7L4cdmWlV7rhFuoVyxUkjtUfexk4"
bot = Bot(token=TOKEN)

async def send_user_notification(telegram_id, text):
    """Отправка уведомления пользователю"""
    if not telegram_id:
        return False

    try:
        await bot.send_message(telegram_id, text, parse_mode='Markdown')
        return True
    except TelegramBadRequest as e:
        print(f"Ошибка отправки пользователю {telegram_id}: {e}")
        return False
