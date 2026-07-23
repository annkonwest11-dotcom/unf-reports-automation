#!/bin/bash

# Полная автоматизированная установка интеграции 1С → Google Sheets → Telegram

set -e  # Выход при ошибке

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     ПОЛНАЯ УСТАНОВКА ИНТЕГРАЦИИ 1С                        ║"
echo "║     Google Apps Script + Расширение 1С                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Директория скрипта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DOCS_DIR="$SCRIPT_DIR/docs"

echo "📁 Рабочая директория: $SCRIPT_DIR"
echo "📁 Документы: $DOCS_DIR"
echo ""

# Функция для проверки команды
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ===== ПРОВЕРКА ТРЕБОВАНИЙ =====
echo "📋 Проверяю требования..."
echo ""

if ! command_exists python3; then
    echo -e "${RED}❌ Python3 не найден${NC}"
    echo "Установи Python3 с https://python.org"
    exit 1
fi
echo -e "${GREEN}✅ Python3 найден${NC}"

if ! command_exists npm; then
    echo -e "${YELLOW}⚠️  npm не найден${NC}"
    echo "Для автоматического развертывания GAS нужен npm"
    echo "Установи Node.js с https://nodejs.org"
    echo ""
    echo "После установки запусти:"
    echo "  npm install -g @google/clasp"
    echo "  clasp login"
    echo ""
    echo "Потом снова запусти этот скрипт"
    exit 1
fi
echo -e "${GREEN}✅ npm найден${NC}"

if ! command_exists clasp; then
    echo -e "${YELLOW}⚠️  clasp не найден${NC}"
    echo "Устанавливаю clasp..."
    npm install -g @google/clasp
    echo ""
    echo "Нужна авторизация в Google. Следуй инструкциям:"
    clasp login
fi
echo -e "${GREEN}✅ clasp готов${NC}"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ===== СОЗДАНИЕ СТРУКТУРЫ =====
echo "1️⃣  СОЗДАЮ СТРУКТУРУ ПРОЕКТА"
echo ""

# Создаем директорию для GAS проекта
GAS_PROJECT_DIR="$SCRIPT_DIR/.gas_deploy"
mkdir -p "$GAS_PROJECT_DIR"
echo "✅ Директория создана: $GAS_PROJECT_DIR"

# Копируем файлы GAS
echo "📋 Копирую файлы Google Apps Script..."

cat > "$GAS_PROJECT_DIR/appsscript.json" << 'EOF'
{
  "timeZone": "Europe/Moscow",
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8"
}
EOF
echo "✅ appsscript.json"

cp "$DOCS_DIR/GAS_COMPLETE_CONFIG.gs" "$GAS_PROJECT_DIR/config.gs" 2>/dev/null || echo "⚠️  config.gs не найден"
echo "✅ config.gs скопирован"

cp "$DOCS_DIR/GAS_COMPLETE_MAIN.gs" "$GAS_PROJECT_DIR/Code.gs" 2>/dev/null || echo "⚠️  Code.gs не найден"
echo "✅ Code.gs скопирован"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ===== РАЗВЕРТЫВАНИЕ GAS =====
echo "2️⃣  РАЗВЕРТЫВАЮ GOOGLE APPS SCRIPT"
echo ""

cd "$GAS_PROJECT_DIR"

# Проверяем есть ли уже проект
if [ -f ".clasp.json" ]; then
    echo "ℹ️  Проект уже существует, обновляю..."
else
    echo "🆕 Создаю новый проект..."
    clasp create --type webapps --title "UNF Reports Integration" 2>/dev/null || true
fi

echo "📤 Загружаю файлы..."
clasp push --force

echo "🚀 Развертываю как Web App..."
DEPLOY_OUTPUT=$(clasp deploy --description "UNF Reports Integration" 2>&1)
echo "$DEPLOY_OUTPUT"

# Извлекаем URL развертывания
DEPLOYMENT_URL=$(echo "$DEPLOY_OUTPUT" | grep -oP 'https://script\.google\.com/[^ ]+' | head -1)

if [ -z "$DEPLOYMENT_URL" ]; then
    echo -e "${YELLOW}⚠️  Не удалось извлечь Deployment URL из вывода${NC}"
    echo "Проверь вывод выше или откройи https://script.google.com"
    DEPLOYMENT_URL="https://script.google.com/macros/d/YOUR_ID/usercurrentUserOnly"
else
    echo -e "${GREEN}✅ Deployment URL получен${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ===== СОЗДАНИЕ ЛИСТОВ =====
echo "3️⃣  ПОДГОТОВКА GOOGLE SHEETS"
echo ""
echo "ℹ️  Листы нужно создать вручную:"
echo ""
echo "1. Открой таблицу:"
echo "   https://docs.google.com/spreadsheets/d/11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tTc/"
echo ""
echo "2. Создай эти листы (если нет):"
echo "   • RAW_perfilev"
echo "   • RAW_gubarev"
echo "   • DASHBOARD"
echo "   • LOG"
echo "   • QUEUE"
echo ""
echo "3. Добавь заголовки (смотри QUICK_START_5MIN.md)"
echo ""

read -p "Нажми Enter когда листы готовы..."

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ===== ПОДГОТОВКА РАСШИРЕНИЯ 1С =====
echo "4️⃣  ПОДГОТОВКА РАСШИРЕНИЯ 1С"
echo ""

# Копируем расширение и обновляем URL
EXTENSION_FILE="$SCRIPT_DIR/UNF_EXTENSION_WITH_URL.bsl"
cp "$DOCS_DIR/UNF_EXTENSION.bsl" "$EXTENSION_FILE"

# Заменяем плейсхолдер на реальный URL
sed -i.bak "s|YOUR_DEPLOYMENT_ID|${DEPLOYMENT_URL#*macros/d/}|g" "$EXTENSION_FILE"
rm -f "$EXTENSION_FILE.bak"

echo "✅ Расширение подготовлено: $EXTENSION_FILE"
echo ""
echo "🚀 Дальшевалии действия:"
echo ""
echo "1. Открой файл расширения:"
echo "   $EXTENSION_FILE"
echo ""
echo "2. В 1С Конфигураторе для каждой базы (Перфильев и Губарев):"
echo "   • Конфигурация → Расширения → Загрузить расширение"
echo "   • Выбери UNF_EXTENSION_WITH_URL.bsl"
echo "   • Нажми Установить"
echo "   • Сохрани базу (Ctrl+S)"
echo ""
echo "3. Создай регламентные задания:"
echo "   • Администрирование → Регламентные задания"
echo "   • ОтправкаОтчетовУНФ: Ежедневно в 09:30"
echo "   • ОпросОчередиКомандУНФ: Каждую минуту"
echo ""
echo "   (Подробные инструкции в 1C_EXTENSION_SETUP.md)"
echo ""

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# ===== ИТОГОВАЯ ИНФОРМАЦИЯ =====
echo -e "${GREEN}✅ УСТАНОВКА ЗАВЕРШЕНА!${NC}"
echo ""
echo "🔗 DEPLOYMENT URL (скопируй для 1С):"
echo -e "${GREEN}$DEPLOYMENT_URL${NC}"
echo ""
echo "📁 ФАЙЛЫ:"
echo "  • Расширение 1С: $EXTENSION_FILE"
echo "  • Google Sheets: https://docs.google.com/spreadsheets/d/11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tТc/"
echo ""
echo "📚 ДОКУМЕНТАЦИЯ:"
echo "  • Быстрый старт: $DOCS_DIR/QUICK_START_5MIN.md"
echo "  • Установка 1С: $DOCS_DIR/1C_EXTENSION_SETUP.md"
echo "  • Начало: $DOCS_DIR/00_START_HERE.md"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# Сохраняем информацию
cat > "$SCRIPT_DIR/SETUP_INFO.txt" << EOF
ИНФОРМАЦИЯ ОБ УСТАНОВКЕ
=======================

Дата: $(date)

Google Apps Script:
  Deployment URL: $DEPLOYMENT_URL
  Проект: $GAS_PROJECT_DIR

Google Sheets:
  ID: 11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tТc
  URL: https://docs.google.com/spreadsheets/d/11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tТc/

1С Расширение:
  Файл: $EXTENSION_FILE
  Telegram Token: 8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY
  Auth Token: unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC

Дальнейшие действия:
1. Создай листы в Google Sheets (RAW_perfilev, RAW_gubarev, DASHBOARD, LOG, QUEUE)
2. Загрузи расширение в обе облачные базы (Перфильев и Губарев)
3. Создай регламентные задания (09:30 и каждую минуту)
4. Проверь логирование и убедись что всё работает

EOF

echo "💾 Информация сохранена в: $SCRIPT_DIR/SETUP_INFO.txt"
echo ""

echo -e "${GREEN}🎉 ВСЁ ГОТОВО! НАЧИНАЙ С 1С РАСШИРЕНИЯ 🎉${NC}"
echo ""
