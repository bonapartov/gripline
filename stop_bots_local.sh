#!/bin/bash
echo "Остановка ботов..."
screen -S admin_bot -X quit 2>/dev/null
screen -S user_bot -X quit 2>/dev/null
echo "Боты остановлены"
