#!/usr/bin/env bash
# Установка борда РОПа на VPS. Запускать на сервере, можно повторно (идемпотентно):
#     ssh -i ~/.ssh/tgbot_vps root@151.243.173.231 'bash /opt/salary-bot/deploy/rop_board_setup.sh'
#
# Что делает:
#   1. /data/board — каталог готовой страницы (её пересобирает cron).
#   2. Монтирует этот каталог в контейнер nginx (jonasal/nginx-certbot) и добавляет
#      в конфиг домена секретный путь /b/<токен>/ — по нему борд и открывается.
#   3. Копирует ключ OpenRouter из orders-bot (разбор комментариев менеджеров).
#   4. Первая сборка страницы + cron: 9:00 МСК со сводкой Анне, далее каждые 2 часа.
# Бэкапы правленых файлов — в /root/nginx/backups/.
set -euo pipefail

SALARY=/opt/salary-bot
BOARD_DIR=/data/board
DOMAIN=django26666.hostkey.in
NGINX_CONF=/data/nginx/user_conf.d/$DOMAIN.conf
COMPOSE=/root/nginx/compose.yml
BACKUPS=/root/nginx/backups
PY=$SALARY/venv/bin/python

echo "== 1. каталог страницы"
mkdir -p "$BOARD_DIR" "$BACKUPS"

if [ ! -s /root/board_token.txt ]; then
    openssl rand -hex 12 > /root/board_token.txt
    chmod 600 /root/board_token.txt
    echo "   токен пути создан"
else
    echo "   токен пути уже есть"
fi
TOKEN=$(cat /root/board_token.txt)
URL="https://$DOMAIN/b/$TOKEN/"

echo "== 2. nginx: монтирование и путь борда"
STAMP=$(date +%F-%H%M)
cp -p "$COMPOSE" "$BACKUPS/compose.yml.$STAMP"
cp -p "$NGINX_CONF" "$BACKUPS/$DOMAIN.conf.$STAMP"

python3 - "$TOKEN" "$COMPOSE" "$NGINX_CONF" <<'PY'
import sys
token, compose, conf = sys.argv[1], sys.argv[2], sys.argv[3]

s = open(compose).read()
if "/data/board" not in s:
    anchor = "      - /data/nginx/user_conf.d:/etc/nginx/user_conf.d"
    if anchor not in s:
        raise SystemExit("не нашёл строку монтирования user_conf.d в compose.yml")
    s = s.replace(anchor, anchor + "\n      - /data/board:/srv/board:ro", 1)
    open(compose, "w").write(s)
    print("   compose.yml: каталог борда смонтирован")
else:
    print("   compose.yml: монтирование уже было")

s = open(conf).read()
if "/srv/board" not in s:
    block = """
    # Борд РОПа — статическая страница, её пересобирает cron (rop_board.py).
    # Путь со случайным токеном: ссылку знают только те, кому её дали.
    location /b/%s/ {
        alias /srv/board/;
        index index.html;
        autoindex off;
        add_header Cache-Control "no-store";
        add_header X-Robots-Tag "noindex, nofollow";
    }

location / {""" % token
    if "\nlocation / {" not in s:
        raise SystemExit("не нашёл блок location / в конфиге домена")
    s = s.replace("\nlocation / {", block, 1)
    open(conf, "w").write(s)
    print("   конфиг домена: путь борда добавлен")
else:
    print("   конфиг домена: путь борда уже был")
PY

echo "== 3. ключ OpenRouter для разбора комментариев"
if grep -q '^OPENROUTER_API_KEY=' "$SALARY/.env"; then
    echo "   ключ уже в .env"
elif grep -q '^OPENROUTER_API_KEY=' /opt/orders-bot/.env; then
    {
        echo ""
        echo "# --- LLM для борда РОПа (тот же ключ OpenRouter, что у orders-bot) ---"
        grep '^OPENROUTER_API_KEY=' /opt/orders-bot/.env
    } >> "$SALARY/.env"
    echo "   ключ скопирован из orders-bot"
else
    echo "   ВНИМАНИЕ: ключа нет — статусы будут только по стадиям Битрикса"
fi

echo "== 4. пересоздание контейнера nginx (секунда простоя)"
cd /root/nginx && docker compose up -d
sleep 4
if docker exec nginx-nginx-1 nginx -t; then
    docker exec nginx-nginx-1 nginx -s reload || true
else
    # конфиг не прошёл проверку — возвращаем как было, сайт не должен пострадать
    echo "   ОШИБКА конфига nginx: откатываю правки"
    cp -p "$BACKUPS/compose.yml.$STAMP" "$COMPOSE"
    cp -p "$BACKUPS/$DOMAIN.conf.$STAMP" "$NGINX_CONF"
    docker compose up -d
    sleep 4
    docker exec nginx-nginx-1 nginx -t && echo "   откат выполнен, сайт работает"
    exit 1
fi

echo "== 5. первая сборка страницы"
cd "$SALARY"
TZ=Europe/Moscow "$PY" rop_board.py --out "$BOARD_DIR/index.html" \
    --json "$BOARD_DIR/data.json" >> "$SALARY/rop_board.log" 2>&1
ls -la "$BOARD_DIR"

echo "== 6. cron"
CRON_MAIN="0 6 * * * cd $SALARY && TZ=Europe/Moscow $PY rop_board.py --out $BOARD_DIR/index.html --json $BOARD_DIR/data.json --notify tg --url $URL >> $SALARY/rop_board.log 2>&1"
CRON_REFRESH="0 8,10,12,14,16 * * * cd $SALARY && TZ=Europe/Moscow $PY rop_board.py --out $BOARD_DIR/index.html --json $BOARD_DIR/data.json >> $SALARY/rop_board.log 2>&1"
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "rop_board.py" > "$TMP" || true
{
    echo "# Борд РОПа: 9:00 МСК — сборка + сводка со ссылкой Анне в Telegram"
    echo "$CRON_MAIN"
    echo "# Борд РОПа: обновление страницы каждые 2 часа, 11:00-19:00 МСК"
    echo "$CRON_REFRESH"
} >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
crontab -l | grep -A1 "Борд РОПа" | head -6

echo
echo "== проверка"
curl -s -o /dev/null -w "   страница: HTTP %{http_code}\n" "$URL"
echo
echo "ГОТОВО. Ссылка на борд:"
echo "   $URL"
echo "Токен пути лежит в /root/board_token.txt. Чтобы сменить ссылку — удалите файл,"
echo "уберите блок location /b/... из $NGINX_CONF и запустите скрипт снова."
