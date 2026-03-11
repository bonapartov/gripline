#!/bin/bash
cd /home/v/Projects/gripline
source venv/bin/activate

echo "Запуск административного бота..."
screen -dmS admin_bot python manage.py run_bot

echo "Запуск пользовательского бота..."
screen -dmS user_bot python manage.py run_user_bot

echo "Боты запущены. Для просмотра:"
echo "  screen -ls                    - список сессий"
echo "  screen -r admin_bot           - логи админ-бота"
echo "  screen -r user_bot            - логи пользовательского бота"
echo "  Ctrl+A затем D                 - отключиться от сессии"
