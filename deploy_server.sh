#!/bin/bash
# deploy.sh - Скрипт развёртывания Gripline для gripline.ru
# Использование: sudo ./deploy.sh

set -e

echo "🚀 Начало развёртывания Gripline..."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_ROOT="/www/wwwroot/gripline.ru"
VENV_PATH="$PROJECT_ROOT/venv"
GUNICORN_PATH="$VENV_PATH/bin/gunicorn"

cd "$PROJECT_ROOT" || exit 1

# 1. Виртуальное окружение
echo -e "${YELLOW}🐍 Виртуальное окружение...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✅ Виртуальное окружение создано${NC}"
else
    echo -e "${GREEN}✅ Виртуальное окружение существует${NC}"
fi

# 2. Установка зависимостей
echo -e "${YELLOW}📦 Установка зависимостей...${NC}"
source "$VENV_PATH/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# Gunicorn отдельно (важно!)
pip install gunicorn

echo -e "${GREEN}✅ Зависимости установлены${NC}"

# Проверка gunicorn
if [ ! -f "$GUNICORN_PATH" ]; then
    echo -e "${RED}❌ Gunicorn не установлен!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Gunicorn: $GUNICORN_PATH${NC}"

# 3. .env файл
echo -e "${YELLOW}🔐 Проверка .env...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env не найден! Создайте файл:${NC}"
    echo "POSTGRES_DB=gripline_prod"
    echo "POSTGRES_USER=gripline_admin"
    echo "POSTGRES_PASSWORD=ваш_пароль"
    echo "POSTGRES_HOST=localhost"
    echo "POSTGRES_PORT=5432"
    echo "SECRET_KEY=ваш_secret_key"
    echo "DEBUG=False"
    echo "ALLOWED_HOSTS=gripline.ru,www.gripline.ru"
    exit 1
else
    echo -e "${GREEN}✅ .env найден${NC}"
fi

# 4. Миграции
echo -e "${YELLOW}🔄 Миграции...${NC}"
python manage.py migrate
echo -e "${GREEN}✅ Миграции применены${NC}"

# 5. Статика
echo -e "${YELLOW}📁 Статика...${NC}"
python manage.py collectstatic --noinput
echo -e "${GREEN}✅ Статика собрана${NC}"

# 6. Импорт данных (если есть скрипты)
for script in import_*.py update_*.py fix_*.py; do
    if [ -f "$script" ]; then
        echo -e "${YELLOW}📊 Выполнение $script...${NC}"
        python "$script" || echo -e "${YELLOW}⚠️  $script завершился с ошибкой${NC}"
    fi
done

# 7. Проверка суперпользователя
echo -e "${YELLOW}👤 Суперпользователь...${NC}"
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    print('⚠️  Суперпользователь не найден!')
    print('   Выполните: python manage.py createsuperuser')
else:
    print('✅ Суперпользователь существует')
"

# 8. Тестовый запуск
echo -e "${YELLOW}🧪 Тестовый запуск...${NC}"
"$GUNICORN_PATH" --workers 2 --bind 127.0.0.1:8000 --timeout 30 mysite.wsgi:application &
GUNICORN_PID=$!
sleep 3

if kill -0 $GUNICORN_PID 2>/dev/null; then
    echo -e "${GREEN}✅ Gunicorn запущен (PID: $GUNICORN_PID)${NC}"
    kill $GUNICORN_PID
else
    echo -e "${RED}❌ Gunicorn не запустился${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ Развёртывание завершено!${NC}"
echo ""
echo -e "${YELLOW}📋 Запуск сервера:${NC}"
echo "   $GUNICORN_PATH --workers 3 --bind 127.0.0.1:8000 mysite.wsgi:application"
echo ""
echo -e "${YELLOW}📋 Systemd сервис:${NC}"
echo "   Скопируйте gripline.service в /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable gripline"
echo "   sudo systemctl start gripline"
echo ""
echo -e "${YELLOW}📋 Перезапуск Nginx:${NC}"
echo "   sudo nginx -t"
echo "   sudo systemctl restart nginx"
echo ""
echo -e "${GREEN}🌐 https://gripline.ru${NC}"
echo -e "${GREEN}🔐 https://gripline.ru/admin/${NC}"
