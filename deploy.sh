#!/bin/bash
# Деплой на продакшн сервер
# Использование: ./deploy.sh
# Запускать ПОСЛЕ git push origin main

set -e

SERVER="root@92.63.192.42"
REMOTE_DIR="/www/wwwroot/gripline.ru"

echo "→ Обновляем код..."
ssh "$SERVER" "cd $REMOTE_DIR && git pull origin main"

echo "→ Обновляем статику..."
ssh "$SERVER" "cd $REMOTE_DIR && source venv/bin/activate && python manage.py collectstatic --noinput"

echo "→ Применяем миграции..."
ssh "$SERVER" "cd $REMOTE_DIR && source venv/bin/activate && python manage.py migrate"

echo "→ Перезапускаем Django..."
ssh "$SERVER" "systemctl restart gripline"

echo "✓ Деплой завершён"
