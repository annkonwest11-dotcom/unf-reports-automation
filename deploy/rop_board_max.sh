#!/usr/bin/env bash
# Утренняя сводка борда РОПа — в MAX вместо Telegram. Запускать на сервере:
#     ssh -i ~/.ssh/tgbot_vps root@151.243.173.231 'bash /opt/salary-bot/deploy/rop_board_max.sh'
#
# Что делает: дописывает в .env адрес личного диалога Анны в MAX и токен бота
# (берёт у obrez-report, он в этом диалоге уже есть), переводит cron на --notify max
# и сразу отправляет пробную сводку, чтобы было видно результат.
set -euo pipefail

SALARY=/opt/salary-bot
BOARD_DIR=/data/board
CHAT_ID=437065504
PY=$SALARY/venv/bin/python
URL="https://django26666.hostkey.in/b/$(cat /root/board_token.txt)/"

echo "== 1. .env"
if grep -q '^MAX_ANNA_CHAT_ID=' "$SALARY/.env"; then
    echo "   MAX_ANNA_CHAT_ID уже есть"
else
    {
        echo ""
        echo "# --- MAX: личный диалог Анны, туда уходит утренняя сводка борда РОПа ---"
        echo "MAX_ANNA_CHAT_ID=$CHAT_ID"
    } >> "$SALARY/.env"
    echo "   MAX_ANNA_CHAT_ID вписан"
fi
if grep -q '^MAX_TOKEN=' "$SALARY/.env"; then
    echo "   MAX_TOKEN уже есть"
else
    grep '^MAX_TOKEN=' /opt/obrez-report/.env >> "$SALARY/.env"
    echo "   MAX_TOKEN скопирован из obrez-report"
fi

echo "== 2. cron: сводка в MAX вместо Telegram"
TMP=$(mktemp)
crontab -l 2>/dev/null | sed 's/--notify tg/--notify max/' > "$TMP"
crontab "$TMP"
rm -f "$TMP"
crontab -l | grep "rop_board.py" | grep -o -- "--notify [a-z]*"

echo "== 3. пробная отправка в MAX"
cd "$SALARY"
TZ=Europe/Moscow "$PY" rop_board.py --out "$BOARD_DIR/index.html" \
    --json "$BOARD_DIR/data.json" --notify max --url "$URL" 2>&1 | tail -3

echo
echo "ГОТОВО. Сводка со ссылкой будет приходить в MAX в 9:00 МСК."
