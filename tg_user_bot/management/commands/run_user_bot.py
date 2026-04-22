import os
import sys
import django
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from teams.models import TeamClaim, TeamManager
from tg_user_bot.models import TelegramUser
from tg_user_bot.notifications import bot

dp = Dispatcher()

# Кнопки
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Проверить заявку")],
        [KeyboardButton(text="🔄 Сбросить email"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

@sync_to_async
def get_saved_email(telegram_id):
    """Получение сохраненного email по Telegram ID"""
    try:
        user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
        return user.email if user else None
    except Exception as e:
        print(f"❌ Ошибка получения email: {e}")
        return None

@sync_to_async
def save_user_email(telegram_id, email):
    """Сохранение email для Telegram ID"""
    try:
        user, created = TelegramUser.objects.update_or_create(
            telegram_id=telegram_id,
            defaults={'email': email}
        )
        print(f"✅ Email {email} сохранен для {telegram_id} (created: {created})")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения email: {e}")
        return False

@sync_to_async
def clear_user_email(telegram_id):
    """Удаление сохраненного email"""
    try:
        deleted, _ = TelegramUser.objects.filter(telegram_id=telegram_id).delete()
        print(f"✅ Email удален для {telegram_id}")
        return True
    except Exception as e:
        print(f"❌ Ошибка удаления email: {e}")
        return False

@sync_to_async
def get_claim_status_by_email(email, telegram_id=None):
    """Получение статуса заявки по email"""
    try:
        users = User.objects.filter(email=email)
        if not users.exists():
            return {
                'status': 'not_found',
                'details': '❌ Пользователь с таким email не найден.'
            }

        user = users.first()

        # Если передан telegram_id - сохраняем его
        if telegram_id:
            manager = TeamManager.objects.filter(user=user).first()
            if manager:
                manager.telegram_id = telegram_id
                manager.telegram_notifications = True
                manager.save()
                print(f"✅ Telegram ID {telegram_id} сохранен в TeamManager")

        # Проверяем менеджера
        manager = TeamManager.objects.filter(user=user).first()
        if manager:
            return {
                'status': 'manager',
                'team': manager.team.name,
                'details': f"✅ Вы руководитель команды *{manager.team.name}*"
            }

        # Проверяем заявку
        claim = TeamClaim.objects.filter(user=user, status='pending').first()
        if claim:
            return {
                'status': 'pending',
                'team': claim.requested_team_name,
                'details': f"⏳ Ваша заявка на команду *{claim.requested_team_name}* ожидает подтверждения"
            }

        return {
            'status': 'no_claims',
            'details': "📭 У вас нет активных заявок"
        }

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {'status': 'error', 'details': '❌ Произошла ошибка'}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветствие с кнопками"""
    await message.answer(
        "👋 Привет! Я бот уведомлений Gripline.\n\n"
        "🔍 Нажмите 'Проверить заявку' - если вы уже вводили email\n"
        "📧 Если первый раз - отправьте email\n"
        "🔄 'Сбросить email' - чтобы привязать новый email",
        reply_markup=main_keyboard
    )

@dp.message(lambda message: message.text == "🔍 Проверить заявку")
async def handle_check_button(message: types.Message):
    """Проверка заявки (с использованием сохраненного email)"""
    telegram_id = message.from_user.id

    # Получаем сохраненный email
    saved_email = await get_saved_email(telegram_id)

    if saved_email:
        # Если email есть - сразу показываем статус
        status = await get_claim_status_by_email(saved_email, telegram_id)
        await message.answer(
            status['details'],
            parse_mode='Markdown',
            reply_markup=main_keyboard
        )
    else:
        # Если email нет - просим ввести
        await message.answer(
            "📧 Я еще не знаю ваш email. Отправьте его мне,\n"
            "чтобы я мог найти вашу заявку.\n\n"
            "Например: ivan@example.com",
            reply_markup=main_keyboard
        )

@dp.message(lambda message: message.text == "🔄 Сбросить email")
async def handle_reset_button(message: types.Message):
    """Сброс сохраненного email"""
    telegram_id = message.from_user.id
    await clear_user_email(telegram_id)
    await message.answer(
        "✅ Email сброшен. Теперь вы можете ввести новый.",
        reply_markup=main_keyboard
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def handle_help_button(message: types.Message):
    """Помощь"""
    await message.answer(
        "📚 Как пользоваться ботом:\n\n"
        "1. 🔍 Проверить заявку - узнать статус (если уже вводили email)\n"
        "2. 📧 Отправьте email - если первый раз\n"
        "3. 🔄 Сбросить email - чтобы привязать новый\n\n"
        "Статусы:\n"
        "⏳ Ожидает подтверждения\n"
        "✅ Заявка одобрена\n"
        "❌ Заявка отклонена",
        reply_markup=main_keyboard
    )

@dp.message(lambda message: '@' in message.text)
async def handle_email(message: types.Message):
    """Обработка email"""
    email = message.text.strip().lower()
    telegram_id = message.from_user.id
    print(f"📩 Получен email: {email} от {telegram_id}")

    # Сохраняем email в базу
    await save_user_email(telegram_id, email)

    # Получаем статус
    status = await get_claim_status_by_email(email, telegram_id)

    await message.answer(
        status['details'],
        parse_mode='Markdown',
        reply_markup=main_keyboard
    )

@dp.message()
async def handle_unknown(message: types.Message):
    """Обработка любых других сообщений"""
    await message.answer(
        "📧 Используйте кнопки меню или отправьте email.",
        reply_markup=main_keyboard
    )

class Command(BaseCommand):
    help = 'Запуск пользовательского бота'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🤖 Пользовательский бот запущен...'))
        self.stdout.write(self.style.SUCCESS('📱 Имя бота: @gripline_bot'))
        asyncio.run(dp.start_polling(bot))
