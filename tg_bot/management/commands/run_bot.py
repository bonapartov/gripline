import os
import sys
import django
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from django.utils import timezone
from datetime import timedelta
from asgiref.sync import sync_to_async
from tg_bot.email_notifications import send_team_claim_approved_email, send_team_claim_rejected_email

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from teams.models import TeamClaim, Team, TeamManager
from tg_bot.models import TelegramUser, PendingAction
from tg_bot.notifications import bot, notify_admins_about_team_claim, ADMIN_IDS, SECRET_CODE
from tg_user_bot.notifications import send_user_notification

dp = Dispatcher()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

@sync_to_async
def get_or_create_telegram_user(telegram_id, first_name, username):
    user, created = TelegramUser.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            'username': username,
            'first_name': first_name,
        }
    )
    if not created:
        user.username = username
        user.first_name = first_name
        user.save()
    return user

@sync_to_async
def get_telegram_user(telegram_id):
    try:
        return TelegramUser.objects.get(telegram_id=telegram_id)
    except TelegramUser.DoesNotExist:
        return None

@sync_to_async
def save_telegram_user(user):
    user.save()
    return user

@sync_to_async
def get_admin_list():
    return list(TelegramUser.objects.filter(is_admin=True))

@sync_to_async
def get_pending_team_claims():
    return list(TeamClaim.objects.filter(status='pending').select_related('user'))

@sync_to_async
def get_similar_teams(team_name, limit=5):
    return list(Team.objects.filter(name__icontains=team_name)[:limit])

@sync_to_async
def get_team_claim(claim_id):
    try:
        return TeamClaim.objects.get(id=claim_id)
    except TeamClaim.DoesNotExist:
        return None

@sync_to_async
def approve_team_claim(claim_id, team_id):
    from teams.models import TeamManager

    claim = TeamClaim.objects.get(id=claim_id)
    team = Team.objects.get(id=team_id)

    old_managers = TeamManager.objects.filter(
        user=claim.user,
        is_active=True
    ).exclude(team=team)

    for old_manager in old_managers:
        old_manager.is_active = False
        old_manager.save()

    claim.team = team
    claim.status = 'approved'
    claim.reviewed_at = timezone.now()
    claim.save()

    manager, created = TeamManager.objects.get_or_create(
        user=claim.user,
        team=team,
        defaults={
            'role': 'captain',
            'is_active': True
        }
    )

    if not created and not manager.is_active:
        manager.is_active = True
        manager.role = 'captain'
        manager.save()

    return claim, team

@sync_to_async
def create_new_team_and_approve(claim_id, team_name):
    from teams.models import TeamManager

    claim = TeamClaim.objects.get(id=claim_id)

    old_managers = TeamManager.objects.filter(
        user=claim.user,
        is_active=True
    )

    for old_manager in old_managers:
        old_manager.is_active = False
        old_manager.save()

    existing_team = Team.objects.filter(name=team_name).first()
    if existing_team:
        team = existing_team
    else:
        team = Team.objects.create(name=team_name)

    claim.team = team
    claim.status = 'approved'
    claim.reviewed_at = timezone.now()
    claim.save()

    manager, created = TeamManager.objects.get_or_create(
        user=claim.user,
        team=team,
        defaults={
            'role': 'captain',
            'is_active': True
        }
    )

    if not created and not manager.is_active:
        manager.is_active = True
        manager.role = 'captain'
        manager.save()

    return claim, team

@sync_to_async
def reject_team_claim(claim_id):
    claim = TeamClaim.objects.get(id=claim_id, status='pending')
    claim.status = 'rejected'
    claim.reviewed_at = timezone.now()
    claim.save()
    return claim

@sync_to_async
def create_pending_action(user, action_type, claim_id, expires_at):
    return PendingAction.objects.create(
        user=user,
        action_type=action_type,
        claim_id=claim_id,
        expires_at=expires_at
    )

# ========== ОБРАБОТЧИК EMAIL (ТОЛЬКО ДЛЯ ПОЛЬЗОВАТЕЛЕЙ) ==========

@dp.message(lambda message: not message.text.startswith('/') and '@' in message.text)
async def handle_email(message: types.Message):
    """Обработка email от пользователей"""
    email = message.text.strip().lower()
    print(f"📩 Получен email: {email}")

    @sync_to_async
    def find_and_bind_user(email, telegram_id):
        try:
            users = User.objects.filter(email=email)
            print(f"🔍 Найдено пользователей: {users.count()}")

            if not users.exists():
                return {'status': 'not_found'}

            for user in users:
                manager = TeamManager.objects.filter(user=user).first()
                if manager:
                    manager.telegram_id = telegram_id
                    manager.telegram_notifications = True
                    manager.save()
                    return {'status': 'manager', 'team': manager.team.name}

                claim = TeamClaim.objects.filter(user=user, status='pending').first()
                if claim:
                    return {'status': 'pending', 'team': claim.requested_team_name}

            return {'status': 'no_claims'}

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return {'status': 'error'}

    result = await find_and_bind_user(email, message.from_user.id)

    if result['status'] == 'manager':
        await message.answer(
            f"✅ Вы менеджер команды *{result['team']}*!\n\n"
            f"Уведомления включены. Я сообщу о любых изменениях.",
            parse_mode='Markdown'
        )
    elif result['status'] == 'pending':
        await message.answer(
            f"⏳ Ваша заявка на команду *{result['team']}* ожидает подтверждения.\n\n"
            f"Как только администратор рассмотрит её, я сообщу.",
            parse_mode='Markdown'
        )
    elif result['status'] == 'no_claims':
        await message.answer(
            "📭 У вас нет активных заявок.\n\n"
            "Если вы подадите заявку на сайте, я пришлю уведомление."
        )
    else:
        await message.answer(
            "❌ Email не найден.\n\n"
            "Убедитесь, что вы ввели тот же email, что и при регистрации."
        )

# ========== АДМИНСКИЕ КОМАНДЫ ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Стартовое сообщение с информацией о боте"""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "пользователь"
    username = message.from_user.username

    tg_user = await get_or_create_telegram_user(user_id, first_name, username)
    is_admin = "✅ Администратор" if tg_user.is_admin else "❌ Не администратор"

    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"Я бот модерации Gripline.\n"
        f"Ваш статус: {is_admin}\n\n"
        f"Доступные команды:\n"
        f"/start - информация о боте\n"
        f"/register <код> - регистрация администратора (для первого входа)\n"
        f"/admin_list - список администраторов\n"
        f"/pending_teams - список ожидающих заявок команд\n"
        f"/add_admin <id> - добавить администратора (только для админов)\n"
        f"/help - помощь"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Помощь"""
    await message.answer(
        "📚 Доступные команды:\n\n"
        "/start - информация о боте\n"
        "/register <код> - регистрация администратора\n"
        "/admin_list - список администраторов\n"
        "/pending_teams - список ожидающих заявок команд\n"
        "/add_admin <id> - добавить администратора\n"
        "/help - помощь"
    )

@dp.message(Command("register"))
async def cmd_register(message: types.Message):
    """Регистрация администратора по секретному коду"""
    user_id = message.from_user.id
    args = message.text.split()

    if len(args) < 2:
        await message.answer("❌ Использование: /register <код>")
        return

    if args[1] != SECRET_CODE:
        await message.answer("❌ Неверный код")
        return

    tg_user = await get_telegram_user(user_id)

    if not tg_user:
        await message.answer("❌ Сначала отправьте /start")
        return

    if tg_user.is_admin:
        await message.answer("❌ Вы уже администратор")
        return

    tg_user.is_admin = True
    await save_telegram_user(tg_user)

    if user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)

    await message.answer(
        "✅ Вы зарегистрированы как администратор!\n\n"
        "Теперь вам доступны команды:\n"
        "/pending_teams - просмотр заявок\n"
        "/admin_list - список администраторов\n"
        "/add_admin - добавление новых администраторов"
    )

@dp.message(Command("admin_list"))
async def cmd_admin_list(message: types.Message):
    """Список администраторов"""
    user_id = message.from_user.id
    tg_user = await get_telegram_user(user_id)

    if not tg_user or not tg_user.is_admin:
        await message.answer("❌ У вас нет прав администратора")
        return

    admins = await get_admin_list()

    if not admins:
        await message.answer("📋 Нет зарегистрированных администраторов")
        return

    text = "📋 Список администраторов:\n\n"
    for admin in admins:
        text += f"• {admin.first_name} (@{admin.username or 'нет'})\n"

    await message.answer(text)

@dp.message(Command("add_admin"))
async def cmd_add_admin(message: types.Message):
    """Добавление администратора (только для админов)"""
    user_id = message.from_user.id
    admin_user = await get_telegram_user(user_id)

    if not admin_user or not admin_user.is_admin:
        await message.answer("❌ У вас нет прав администратора")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /add_admin <telegram_id>")
        return

    try:
        new_admin_id = int(args[1])

        if new_admin_id == user_id:
            await message.answer("❌ Нельзя добавить самого себя")
            return

        new_admin = await get_telegram_user(new_admin_id)

        if not new_admin:
            await message.answer("❌ Пользователь не найден. Сначала он должен отправить /start")
            return

        if new_admin.is_admin:
            await message.answer("❌ Этот пользователь уже является администратором")
            return

        new_admin.is_admin = True
        await save_telegram_user(new_admin)

        if new_admin_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin_id)

        await message.answer(f"✅ Пользователь {new_admin.first_name} (@{new_admin.username}) назначен администратором")

        try:
            await bot.send_message(
                new_admin_id,
                f"✅ Вас назначили администратором бота Gripline!\n"
                f"Назначил: {admin_user.first_name}\n\n"
                f"Используйте /help для списка команд"
            )
        except:
            pass

    except ValueError:
        await message.answer("❌ Неверный формат ID")

@dp.message(Command("pending_teams"))
async def cmd_pending_teams(message: types.Message):
    """Список ожидающих заявок команд"""
    user_id = message.from_user.id
    tg_user = await get_telegram_user(user_id)

    if not tg_user or not tg_user.is_admin:
        await message.answer("❌ У вас нет прав администратора")
        return

    pending_claims = await get_pending_team_claims()

    if not pending_claims:
        await message.answer("📋 Нет ожидающих заявок от команд")
        return

    for claim in pending_claims:
        similar_teams = await get_similar_teams(claim.requested_team_name, 3)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"team_approve_{claim.id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"team_reject_{claim.id}")]
        ])

        text = (
            f"🔔 Заявка #{claim.id}\n"
            f"📧 Email: {claim.user.email}\n"
            f"🏁 Команда: {claim.requested_team_name}\n"
            f"📅 Дата: {claim.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )

        if similar_teams:
            text += "\nПохожие команды:\n"
            for team in similar_teams:
                text += f"• {team.name}\n"

        await message.answer(text, reply_markup=keyboard)

# ========== ОБРАБОТЧИКИ КНОПОК ==========

@dp.callback_query(lambda c: c.data.startswith('team_approve_'))
async def process_team_approve(callback: types.CallbackQuery):
    claim_id = int(callback.data.split('_')[2])
    claim = await get_team_claim(claim_id)

    if not claim or claim.status != 'pending':
        await callback.message.edit_text("❌ Заявка уже обработана")
        return

    @sync_to_async
    def get_user_email(claim):
        return claim.user.email

    user_email = await get_user_email(claim)

    admin_user = await get_telegram_user(callback.from_user.id)
    if admin_user:
        await create_pending_action(
            admin_user,
            'team_approve',
            claim_id,
            timezone.now() + timedelta(hours=24)
        )

    similar_teams = await get_similar_teams(claim.requested_team_name, 5)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать новую", callback_data=f"team_create_new_{claim_id}")]
    ])

    for team in similar_teams:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"✅ {team.name}",
                callback_data=f"team_select_{claim_id}_{team.id}"
            )
        ])

    await callback.message.edit_text(
        f"Выберите команду для пользователя {user_email}:\n"
        f"Запрошено: {claim.requested_team_name}",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('team_select_'))
async def select_existing_team(callback: types.CallbackQuery):
    parts = callback.data.split('_')

    if len(parts) != 4:
        await callback.message.edit_text("❌ Ошибка формата данных")
        return

    claim_id = int(parts[2])
    team_id = int(parts[3])

    try:
        claim, team = await approve_team_claim(claim_id, team_id)

        @sync_to_async
        def send_email():
            send_team_claim_approved_email(claim.user, team)
        await send_email()

        @sync_to_async
        def get_telegram_id(user):
            manager = TeamManager.objects.filter(user=user).first()
            if manager and manager.telegram_id and manager.telegram_notifications:
                return manager.telegram_id
            return None

        telegram_id = await get_telegram_id(claim.user)

        if telegram_id:
            text = (
                f"✅ Заявка на команду *{team.name}* подтверждена!\n\n"
                f"Вход: http://127.0.0.1:8000/teams/login/\n"
                f"Страница: http://127.0.0.1:8000/teams/{team.slug}/"
            )

            # ИСПРАВЛЕНИЕ: импортируем и используем функцию из пользовательского бота
            from tg_user_bot.notifications import send_user_notification
            await send_user_notification(telegram_id, text)

        await callback.message.edit_text(
            f"✅ Заявка подтверждена!\n"
            f"Пользователь {claim.user.email} → {team.name}"
        )
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        await callback.message.edit_text("❌ Ошибка")

@dp.callback_query(lambda c: c.data.startswith('team_create_new_'))
async def create_new_team(callback: types.CallbackQuery):
    parts = callback.data.split('_')

    if len(parts) != 4:
        await callback.message.edit_text("❌ Ошибка формата данных")
        return

    claim_id = int(parts[3])

    try:
        claim = await get_team_claim(claim_id)
        if not claim:
            await callback.message.edit_text("❌ Заявка не найдена")
            return

        claim, team = await create_new_team_and_approve(claim_id, claim.requested_team_name)

        @sync_to_async
        def send_email():
            send_team_claim_approved_email(claim.user, team)
        await send_email()

        await callback.message.edit_text(
            f"✅ Создана новая команда {team.name}\n"
            f"Капитан: {claim.user.email}"
        )

    except Exception as e:
        await callback.message.edit_text("❌ Ошибка")

@dp.callback_query(lambda c: c.data.startswith('team_reject_'))
async def process_team_reject(callback: types.CallbackQuery):
    claim_id = int(callback.data.split('_')[2])

    try:
        claim = await reject_team_claim(claim_id)

        @sync_to_async
        def send_email():
            send_team_claim_rejected_email(
                claim.user,
                claim.requested_team_name,
                "Отклонено администратором"
            )
        await send_email()

        await callback.message.edit_text(
            f"❌ Заявка отклонена\n"
            f"Пользователь: {claim.user.email}"
        )

    except TeamClaim.DoesNotExist:
        await callback.message.edit_text("❌ Заявка уже обработана")

# ========== ЗАПУСК ==========

class Command(BaseCommand):
    help = 'Запуск Telegram бота для модерации'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🤖 Telegram бот запускается...'))

        global ADMIN_IDS
        admin_ids = list(TelegramUser.objects.filter(
            is_admin=True
        ).values_list('telegram_id', flat=True))

        ADMIN_IDS.clear()
        ADMIN_IDS.extend(admin_ids)

        self.stdout.write(self.style.SUCCESS(f'✅ Загружено администраторов: {len(admin_ids)}'))
        self.stdout.write(self.style.SUCCESS('🚀 Бот запущен и готов к работе!'))

        asyncio.run(dp.start_polling(bot))
