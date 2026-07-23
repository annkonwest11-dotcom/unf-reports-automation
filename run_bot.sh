#!/bin/bash

echo "🤖 Запускаю бот с автоповтором каждые 5 минут..."
echo "⏳ Ждём пока Telegram отпустит соединение..."

source venv/bin/activate

RETRY_COUNT=0
MAX_RETRIES=24  # 24 * 5 минут = 2 часа

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo ""
    echo "Попытка $((RETRY_COUNT + 1))/$MAX_RETRIES"

    # Kill old process
    pkill -9 -f "python3 bot.py" 2>/dev/null
    sleep 2

    # Start bot
    nohup python3 bot.py > bot_session.log 2>&1 &
    sleep 5

    # Check if running
    if ps aux | grep "python3 bot.py" | grep -v grep > /dev/null; then
        echo "✅ БОТ УСПЕШНО ЗАПУЩЕН!"
        tail -10 bot_session.log
        exit 0
    else
        # Check if it's Telegram conflict
        if grep -q "Conflict: terminated by other getUpdates" bot_session.log; then
            echo "⏳ Telegram ещё блокирует, ждём 5 минут..."
            RETRY_COUNT=$((RETRY_COUNT + 1))
            sleep 300  # 5 минут
        else
            echo "❌ Другая ошибка. Проверь логи:"
            tail -20 bot_session.log
            exit 1
        fi
    fi
done

echo "❌ Не удалось запустить бот после $MAX_RETRIES попыток"
tail -20 bot_session.log
