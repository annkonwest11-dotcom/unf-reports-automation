#!/usr/bin/env python3
"""
Автоматическое развертывание Google Apps Script Web App
Выполняет все необходимые шаги через Google API
"""

import os
import json
import subprocess
import sys
from pathlib import Path

# Конфигурация
GAS_CONFIG = """// gas_config.gs
/**
 * GOOGLE APPS SCRIPT - КОНФИГУРАЦИЯ
 * 1С → Google Sheets → Telegram интеграция
 */

const REAL_CONFIG = {
  TELEGRAM_TOKEN: '8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY',
  SPREADSHEET_ID: '11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tTc',
  AUTH_TOKEN: 'unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC',
};

const getConfig = () => {
  const props = PropertiesService.getScriptProperties();
  return {
    TELEGRAM_TOKEN: props.getProperty('TELEGRAM_TOKEN') || REAL_CONFIG.TELEGRAM_TOKEN,
    SPREADSHEET_ID: props.getProperty('SPREADSHEET_ID') || REAL_CONFIG.SPREADSHEET_ID,
    AUTH_TOKEN: props.getProperty('AUTH_TOKEN') || REAL_CONFIG.AUTH_TOKEN,
  };
};

const ALLOWED_CHATS = {
  'anna': 796207056,
};

const SCHEDULE = {
  DAILY_TIME: '09:30',
  WEEKLY_DAY: 1,
  WEEKLY_TIME: '09:00',
  MONTHLY_DAY: 1,
  MONTHLY_TIME: '09:00',
};

const SHEET_NAMES = {
  RAW_PERFILEV: 'RAW_perfilev',
  RAW_GUBAREV: 'RAW_gubarev',
  DASHBOARD: 'DASHBOARD',
  LOG: 'LOG',
  QUEUE: 'QUEUE',
};

const CELL_MAP = {
  'sales_total': { perfilev: 'C5', gubarev: 'D5', total: 'E5' },
  'sales_dynamics_pct': { perfilev: 'C6', gubarev: 'D6', total: 'E6' },
  'sales_avg_per_day': { perfilev: 'C7', gubarev: 'D7', total: 'E7' },
  'sales_forecast': { perfilev: 'C8', gubarev: 'D8', total: 'E8' },
  'settlements_they_owe': { perfilev: 'C11', gubarev: 'D11', total: 'E11' },
  'settlements_we_owe': { perfilev: 'C12', gubarev: 'D12', total: 'E12' },
  'receivables_total': { perfilev: 'C15', gubarev: 'D15', total: 'E15' },
  'receivables_overdue': { perfilev: 'C16', gubarev: 'D16', total: 'E16' },
  'period_start': 'B2',
  'period_end': 'B3',
  'generated_at': 'B4',
};

const TIMEOUT_MINUTES = 15;
const TOP_N = 5;
const TIME_ZONE = 'Europe/Moscow';
const CURRENCY_FORMAT = '₽';

const BASES = {
  perfilev: { name: 'ИП Перфильев', id: 'perfilev' },
  gubarev: { name: 'ИП Губарев', id: 'gubarev' },
};

const log = (message) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.log(`[${timestamp}] ${message}`);
};

const logError = (message, error) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.error(`[${timestamp}] ERROR: ${message}`);
  if (error) {
    console.error(error.stack || error.toString());
  }
};

const formatMoney = (amount) => {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(amount);
};

const formatDate = (dateStr) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ru-RU');
};

const generateUUID = () => {
  return Utilities.getUuid();
};

const getSpreadsheet = () => {
  return SpreadsheetApp.openById(getConfig().SPREADSHEET_ID);
};

const getSheet = (sheetName) => {
  return getSpreadsheet().getSheetByName(sheetName);
};
"""

class GASDeployer:
    def __init__(self):
        self.project_dir = Path.home() / ".gas_project"
        self.project_dir.mkdir(exist_ok=True)

    def print_banner(self):
        print("""
╔════════════════════════════════════════════════════════════╗
║   Автоматическое развертывание Google Apps Script Web App  ║
║   1С → Google Sheets → Telegram интеграция                 ║
╚════════════════════════════════════════════════════════════╝
        """)

    def check_requirements(self):
        """Проверить наличие необходимых инструментов"""
        print("📋 Проверяю требования...\n")

        # Проверяем clasp (Google Apps Script CLI)
        try:
            result = subprocess.run(['clasp', '--version'], capture_output=True)
            print("✅ clasp установлен:", result.stdout.decode().strip())
        except FileNotFoundError:
            print("""
❌ clasp не найден!

Для автоматического развертывания нужен clasp:
https://github.com/google/clasp

Установи через npm:
    npm install -g @google/clasp

Затем запусти:
    clasp login

И снова запусти этот скрипт.
            """)
            return False

        return True

    def create_project_structure(self):
        """Создать структуру проекта"""
        print("\n📁 Создаю структуру проекта...\n")

        project_files = {
            'appsscript.json': json.dumps({
                "timeZone": "Europe/Moscow",
                "exceptionLogging": "STACKDRIVER",
                "runtimeVersion": "V8",
                "dependencies": {
                    "libraries": []
                }
            }, indent=2),

            'config.gs': GAS_CONFIG,
        }

        for filename, content in project_files.items():
            filepath = self.project_dir / filename
            filepath.write_text(content, encoding='utf-8')
            print(f"✅ Создан: {filename}")

        print("\n✅ Структура проекта готова\n")

    def deploy(self):
        """Развернуть приложение"""
        print("🚀 Развертываю Google Apps Script Web App...\n")

        os.chdir(self.project_dir)

        try:
            # Создать новый проект
            print("1️⃣  Создаю новый GAS проект...")
            result = subprocess.run(['clasp', 'create', '--type', 'webapps'],
                                  capture_output=True, text=True)

            if result.returncode != 0:
                # Проект может уже существовать
                print("⚠️  Используется существующий проект")
            else:
                print("✅ Проект создан\n")

            # Загрузить файлы
            print("2️⃣  Загружаю файлы...")
            result = subprocess.run(['clasp', 'push'],
                                  capture_output=True, text=True)

            if result.returncode == 0:
                print("✅ Файлы загружены\n")
            else:
                print("❌ Ошибка загрузки:", result.stderr)
                return False

            # Развернуть
            print("3️⃣  Развертываю как Web App...")
            result = subprocess.run(['clasp', 'deploy', '--description', 'UNF Reports Integration'],
                                  capture_output=True, text=True)

            if result.returncode == 0:
                output = result.stdout + result.stderr

                # Извлечь URL развертывания
                if 'https://script.google.com' in output:
                    lines = output.split('\n')
                    for line in lines:
                        if 'https://script.google.com' in line:
                            deployment_url = line.strip()
                            if deployment_url.startswith('-'):
                                deployment_url = deployment_url[1:].strip()

                            print(f"✅ Развернуто!\n")
                            print("🔗 Deployment URL:")
                            print(f"   {deployment_url}\n")

                            # Сохранить URL
                            self.save_deployment_url(deployment_url)
                            return True

                print("✅ Развернуто (но не удалось извлечь URL)")
                print("   Проверь вывод выше или откройи: https://script.google.com\n")
                return True
            else:
                print("❌ Ошибка развертывания:", result.stderr)
                return False

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False

    def save_deployment_url(self, url):
        """Сохранить URL для использования"""
        config_file = Path.home() / '.gas_deployment.txt'
        config_file.write_text(url)
        print(f"💾 URL сохранен в: {config_file}")

    def create_spreadsheet_structure(self):
        """Создать структуру листов в Google Sheets"""
        print("\n📊 Создаю структуру листов в Google Sheets...\n")

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            print("""
⚠️  Для этого нужны Google API Python библиотеки:
    pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
            """)
            return False

        sheet_id = '11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tTc'

        # TODO: Реализовать через Sheets API если нужно
        print("ℹ️  Листы нужно создать вручную через Google Sheets UI")
        print("   Или используй файл QUICK_START_5MIN.md\n")

        return True

    def run(self):
        """Запустить весь процесс"""
        self.print_banner()

        if not self.check_requirements():
            sys.exit(1)

        self.create_project_structure()

        if not self.deploy():
            print("\n❌ Развертывание не удалось")
            sys.exit(1)

        print("""
═══════════════════════════════════════════════════════════

✅ GOOGLE APPS SCRIPT УСПЕШНО РАЗВЕРНУТ!

Дальше нужно:

1️⃣  Подготовить Google Sheets:
    - Открой таблицу
    - Создай листы: RAW_perfilev, RAW_gubarev, DASHBOARD, LOG, QUEUE
    - Скопируй инструкцию из QUICK_START_5MIN.md

2️⃣  Загрузить расширение в 1С:
    - Используй файл UNF_EXTENSION.bsl
    - Вставь Deployment URL из вывода выше
    - Следуй инструкции в 1C_EXTENSION_SETUP.md

═══════════════════════════════════════════════════════════
        """)

if __name__ == "__main__":
    deployer = GASDeployer()
    deployer.run()
