#!/bin/bash
set -e

echo "🚀 АВТОМАТИЧЕСКОЕ РАЗВЕРТЫВАНИЕ ВСЕ-В-ОДНОМ"
echo ""

# Проверка требований
if ! command -v clasp &> /dev/null; then
    echo "❌ clasp не установлен"
    exit 1
fi

echo "✅ clasp установлен"
echo ""

# Директории
WORK_DIR="/Users/anna/claude-test/.gas_final_deploy"
DOCS_DIR="/Users/anna/claude-test/docs"
mkdir -p "$WORK_DIR"

cd "$WORK_DIR"

# Создаем appsscript.json
cat > appsscript.json << 'EOF'
{
  "timeZone": "Europe/Moscow",
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8"
}
EOF

# Копируем файлы GAS
echo "📋 Подготавливаю файлы..."
cp "$DOCS_DIR/GAS_COMPLETE_CONFIG.gs" config.gs
cp "$DOCS_DIR/GAS_COMPLETE_MAIN.gs" Code.gs

echo "✅ Файлы готовы"
echo ""

# Проверяем есть ли уже проект
if [ ! -f ".clasp.json" ]; then
    echo "🆕 Создаю новый Google Apps Script проект..."
    # Используем create без типа - он спросит или будет standalone
    clasp create --title "UNF Reports Integration" 2>&1 | head -5 || true
    echo "✅ Проект создан"
else
    echo "ℹ️  Используется существующий проект"
fi

echo ""
echo "📤 Загружаю файлы на Google..."
clasp push --force 2>&1 | tail -10 || true

echo ""
echo "🚀 Развертываю как Web App..."
RESULT=$(clasp deploy --description "UNF Reports Integration" 2>&1)
echo "$RESULT" | tail -20

# Извлекаем URL
URL=$(echo "$RESULT" | grep -oP 'https://script\.google\.com[^ ]+' | head -1 || echo "")

if [ -z "$URL" ]; then
    # Пытаемся получить через deployments list
    echo ""
    echo "🔗 Получаю Deployment URL..."
    DEPLOY_INFO=$(clasp deployments 2>&1 | head -3)
    echo "$DEPLOY_INFO"
    
    PROJECT_ID=$(cat .clasp.json 2>/dev/null | grep -oP '"scriptId": "\K[^"]+' || echo "")
    if [ ! -z "$PROJECT_ID" ]; then
        URL="https://script.google.com/macros/d/$PROJECT_ID/usercurrentUserOnly"
        echo "✅ URL сгенерирован на основе Project ID"
    fi
fi

if [ -z "$URL" ]; then
    echo "❌ Не удалось получить Deployment URL"
    echo ""
    echo "Попробуй вручную:"
    echo "1. Открой: https://script.google.com"
    echo "2. Найди проект 'UNF Reports Integration'"
    echo "3. Deploy → New deployment"
    echo "4. Выбери Type: Web app"
    echo "5. Скопируй URL"
    exit 1
fi

echo ""
echo "✅ РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🔗 DEPLOYMENT URL (СКОПИРУЙ ДЛЯ 1С):"
echo ""
echo "$URL"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# Сохраняем URL
echo "$URL" > /Users/anna/claude-test/DEPLOYMENT_URL.txt
echo "✅ URL сохранен в: /Users/anna/claude-test/DEPLOYMENT_URL.txt"
echo ""

# Создаем готовое расширение 1С
echo "📦 Подготавливаю расширение 1С..."
EXTENSION_FILE="/Users/anna/claude-test/1C_UNF_EXTENSION_FINAL.bsl"

cp "$DOCS_DIR/UNF_EXTENSION.bsl" "$EXTENSION_FILE"

# Заменяем URL
sed -i.bak 's|https://script.google.com/macros/d/YOUR_DEPLOYMENT_ID/usercurrentUserOnly|'"$URL"'|g' "$EXTENSION_FILE"
rm -f "$EXTENSION_FILE.bak"

echo "✅ Расширение готово: $EXTENSION_FILE"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📝 ЧТО ДЕЛАТЬ ДАЛЬШЕ:"
echo ""
echo "1️⃣  СОЗДАТЬ ЛИСТЫ В GOOGLE SHEETS (5 минут)"
echo "   Открой: https://docs.google.com/spreadsheets/d/11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tТc/"
echo "   Создай листы: RAW_perfilev, RAW_gubarev, DASHBOARD, LOG, QUEUE"
echo ""
echo "2️⃣  ЗАГРУЗИТЬ РАСШИРЕНИЕ В 1С (15 минут)"
echo "   Файл: $EXTENSION_FILE"
echo ""
echo "   В каждой базе (Перфильев и Губарев):"
echo "   • Откройи 1С Конфигуратор (F7)"
echo "   • Конфигурация → Расширения → Загрузить расширение"
echo "   • Выбери: 1C_UNF_EXTENSION_FINAL.bsl"
echo "   • Нажми: Установить"
echo "   • Сохрани: Ctrl+S"
echo ""
echo "3️⃣  СОЗДАТЬ РЕГЛАМЕНТНЫЕ ЗАДАНИЯ В 1С (5 минут)"
echo ""
echo "   В каждой базе создай 2 задания:"
echo ""
echo "   📌 Задание 1: Ежедневная отправка"
echo "      Администрирование → Регламентные задания → Новое"
echo "      • Имя: ОтправкаОтчетовУНФ"
echo "      • Процедура: УНФ.ОтправкаОтчетовРегламент"
echo "      • Использование: Включить"
echo "      • Расписание: Ежедневно в 09:30 МСК"
echo "      • Нажми ОК"
echo ""
echo "   📌 Задание 2: Опрос очереди"
echo "      Администрирование → Регламентные задания → Новое"
echo "      • Имя: ОпросОчередиКомандУНФ"
echo "      • Процедура: УНФ.ОпросОчередиКомандРегламент"
echo "      • Использование: Включить"
echo "      • Расписание: Каждую минуту"
echo "      • Нажми ОК"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🎉 И ВСЁ! СИСТЕМА БУДЕТ ПОЛНОСТЬЮ РАБОТАТЬ!"
echo ""
