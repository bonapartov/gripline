from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

TOKEN = "8711872551:AAGMCrKGE4Xx-smOj54QOIH1ix9rG0rIw_I"
SECRET_CODE = "GriplineAdmin2025"

bot = Bot(token=TOKEN)
ADMIN_IDS = []

async def notify_admins_about_team_claim(claim):
    """Уведомление админов о новой заявке команды"""
    from website.models import Team

    global ADMIN_IDS

    if not ADMIN_IDS:
        # Загружаем админов из базы
        from tg_bot.models import TelegramUser

        @sync_to_async
        def load_admins():
            return list(TelegramUser.objects.filter(
                is_admin=True
            ).values_list('telegram_id', flat=True))

        from asgiref.sync import sync_to_async
        ADMIN_IDS = await load_admins()

    if not ADMIN_IDS:
        return

    # Находим похожие команды
    @sync_to_async
    def get_similar_teams():
        return list(Team.objects.filter(
            name__icontains=claim.requested_team_name
        )[:5])

    similar_teams = await get_similar_teams()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"team_approve_{claim.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"team_reject_{claim.id}")]
    ])

    @sync_to_async
    def get_user_email():
        return claim.user.email

    user_email = await get_user_email()

    text = (
        f"🔔 Новая заявка от команды!\n\n"
        f"📧 Email: {user_email}\n"
        f"🏁 Команда: {claim.requested_team_name}\n"
        f"📅 Дата: {claim.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    )

    if similar_teams:
        text += "Похожие команды в базе:\n"
        for team in similar_teams:
            text += f"• {team.name}\n"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=keyboard)
        except:
            pass

async def send_telegram_notification(telegram_id, text, keyboard=None):
    """Отправка уведомления в Telegram"""
    from aiogram.exceptions import TelegramBadRequest

    if not telegram_id:
        return False

    try:
        await bot.send_message(
            telegram_id,
            text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return True
    except TelegramBadRequest as e:
        print(f"Ошибка отправки в Telegram (ID {telegram_id}): {e}")
        return False
    except Exception as e:
        print(f"Неизвестная ошибка Telegram: {e}")
        return False
