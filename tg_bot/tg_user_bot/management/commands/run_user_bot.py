import os
import sys
import django
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from teams.models import TeamClaim, TeamManager
from tg_user_bot.notifications import bot

dp = Dispatcher()

@sync_to_async
def find_user_by_email(email):
    """Поиск пользователя по email"""
    try:
        users = User.objects.filter(email=email)
        print(f"🔍 Найдено пользователей: {users.count()}")

        if not users.exists():
            return None

        for user in users:
            manager = TeamManager.objects.filter(user=user).first()
            if manager:
                return {
                    'type': 'manager',
                    'team': manager.team.name,
                    'user': user,
                    'telegram_id': manager.telegram_id
                }

            claim = TeamClaim.objects.filter(user=user, status='pending').first()
            if claim:
                return {
                    'type': 'pending',
                    'team': claim.requested_team_name,
                    'user': user
                }

        return {'type': 'no_claims', 'user': users.first()}
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

@sync_to_async
def bind_telegram_id(user, telegram_id):
    """Привязка Telegram ID к пользователю"""
    manager = TeamManager.objects.filter(user=user).first()
    if manager:
        old_id = manager.telegram_id
        manager.telegram_id = telegram_id
        manager.telegram_notifications = True
        manager.save()
        print(f"✅ Telegram ID привязан: {old_id} → {telegram_id}")
        return True

    # Если нет менеджера, но есть пользователь - создаем запись?
    # Пока просто возвращаем False
    return False

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветствие"""
    await message.answer(
        "👋 Привет! Я бот уведомлений Gripline.\n\n"
        "📧 Отправьте мне email, который вы указали при регистрации,\n"
        "и я буду присылать уведомления о статусе вашей заявки."
    )

@dp.message(lambda message: '@' in message.text)
async def handle_email(message: types.Message):
    """Обработка email"""
    email = message.text.strip().lower()
    telegram_id = message.from_user.id
    print(f"📩 Получен email: {email} от {telegram_id}")

    result = await find_user_by_email(email)

    if not result:
        await message.answer(
            "❌ Пользователь с таким email не найден.\n\n"
            "Убедитесь, что вы ввели тот же email, что и при регистрации."
        )
        return

    # Привязываем Telegram ID
    bind_result = await bind_telegram_id(result['user'], telegram_id)

    if result['type'] == 'manager':
        status_text = f"✅ Вы менеджер команды *{result['team']}*!"
        if result.get('telegram_id') and result['telegram_id'] != telegram_id:
            status_text += "\n\n🔄 Telegram ID обновлен."
    elif result['type'] == 'pending':
        status_text = f"⏳ Ваша заявка на команду *{result['team']}* ожидает подтверждения."
    else:
        status_text = "📭 У вас нет активных заявок."

    await message.answer(
        f"{status_text}\n\n"
        f"Уведомления {'включены' if bind_result else 'не настроены'}. "
        f"Я сообщу о любых изменениях.",
        parse_mode='Markdown'
    )

@dp.message()
async def handle_unknown(message: types.Message):
    """Обработка любых других сообщений"""
    await message.answer(
        "📧 Отправьте мне email, который вы использовали при регистрации.\n"
        "Например: ivan@example.com"
    )

class Command(BaseCommand):
    help = 'Запуск пользовательского бота'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🤖 Пользовательский бот запущен...'))
        self.stdout.write(self.style.SUCCESS('📱 Имя бота: @gripline_bot'))
        asyncio.run(dp.start_polling(bot))
