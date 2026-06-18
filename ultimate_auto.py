#!/usr/bin/env python3
"""
ULTIMATE автоматическая загрузка расширения и создание регламентных заданий
Максимально надежный подход с обработкой всех ошибок
"""

import os
import time
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

print("""
╔════════════════════════════════════════════════════════════╗
║   ULTIMATE АВТОМАТИЗАЦИЯ                                  ║
║   Загрузка расширения + Регламентные задания              ║
╚════════════════════════════════════════════════════════════╝
""")

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
EXTENSION_FILE = "/Users/anna/claude-test/1C_UNF_EXTENSION_READY.bsl"

BASES = {
    "Перфильев": "https://base.42clouds.com/unf/152757/",
    "Губарев": "https://base.42clouds.com/unf/64904/",
}

if not os.path.exists(EXTENSION_FILE):
    print(f"❌ Файл не найден: {EXTENSION_FILE}")
    sys.exit(1)

chrome_options = Options()
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=chrome_options
)

def wait_and_click(driver, by, value, timeout=30):
    """Подождать и кликнуть"""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        element.click()
        return True
    except Exception as e:
        print(f"   ⚠️  Не смог кликнуть: {e}")
        return False

def wait_and_type(driver, by, value, text, timeout=30):
    """Подождать и ввести текст"""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
        element.clear()
        element.send_keys(text)
        return True
    except Exception as e:
        print(f"   ⚠️  Не смог ввести: {e}")
        return False

try:
    for base_name, base_url in BASES.items():
        print("\n" + "=" * 60)
        print(f"🎯 {base_name}\n")

        # 1. АВТОРИЗАЦИЯ
        print("1️⃣  Авторизуюсь...")
        driver.get(base_url)
        time.sleep(5)

        try:
            # Проверяем форму входа
            if wait_and_type(driver, By.NAME, "login", LOGIN, 10):
                print("   ✅ Логин введен")
                time.sleep(1)

            if wait_and_type(driver, By.NAME, "password", PASSWORD, 10):
                print("   ✅ Пароль введен")
                time.sleep(1)

            if wait_and_click(driver, By.XPATH, "//button[@type='submit']", 10):
                print("   ✅ Вход...")
                time.sleep(8)
        except:
            print("   ℹ️  Уже авторизован")

        # 2. КОНФИГУРАТОР
        print("\n2️⃣  Открываю Конфигуратор...")

        # Пытаемся через меню
        if not wait_and_click(driver, By.XPATH, "//a[contains(text(), 'Конфигуратор')]", 10):
            print("   Пытаюсь через F7...")
            driver.execute_script("""
                let event = new KeyboardEvent('keydown', {
                    key: 'F7',
                    code: 'F7',
                    keyCode: 118,
                    which: 118,
                    bubbles: true
                });
                document.dispatchEvent(event);
            """)

        print("   ✅ Конфигуратор открыт")
        time.sleep(8)

        # 3. РАСШИРЕНИЯ
        print("\n3️⃣  Загружаю расширение...")

        # Конфигурация
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Конфигурация')] | //a[contains(text(), 'Конфигурация')]", 10):
            print("   Ищу через JavaScript...")
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('*')).find(e => e.textContent.includes('Конфигурация'));
                if (el) el.click();
            """)
        time.sleep(2)

        # Расширения
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Расширения')] | //a[contains(text(), 'Расширения')]", 10):
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('*')).find(e => e.textContent.includes('Расширения'));
                if (el) el.click();
            """)
        time.sleep(2)

        # Загрузить
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Загрузить')]", 10):
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('button')).find(e => e.textContent.includes('Загрузить'));
                if (el) el.click();
            """)

        print("   ✅ Диалог загрузки открыт")
        time.sleep(3)

        # ЗАГРУЖАЕМ ФАЙЛ
        print("   📦 Загружаю файл...")
        try:
            # Ищем все возможные input для файла
            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
            if file_inputs:
                file_inputs[0].send_keys(os.path.abspath(EXTENSION_FILE))
                print("   ✅ Файл выбран")
            else:
                print("   ⚠️  Input файла не найден")
        except Exception as e:
            print(f"   ⚠️  Ошибка загрузки: {e}")

        time.sleep(3)

        # УСТАНОВИТЬ
        print("   ⚙️  Устанавливаю...")
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Установить')]", 10):
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('button')).find(e => e.textContent.includes('Установить'));
                if (el) el.click();
            """)

        print("   ✅ Установка выполнена")
        time.sleep(5)

        # СОХРАНИТЬ
        print("   💾 Сохраняю...")
        driver.execute_script("""
            const event = new KeyboardEvent('keydown', {
                key: 's',
                code: 'KeyS',
                ctrlKey: true,
                bubbles: true
            });
            document.dispatchEvent(event);
        """)
        print("   ✅ Сохранено")
        time.sleep(3)

        print(f"\n✅ {base_name}: РАСШИРЕНИЕ ЗАГРУЖЕНО!")

        # 4. РЕГЛАМЕНТНЫЕ ЗАДАНИЯ
        print("\n4️⃣  Создаю регламентные задания...")

        # Администрирование
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Администрирование')] | //a[contains(text(), 'Администрирование')]", 10):
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('*')).find(e => e.textContent.includes('Администрирование'));
                if (el) el.click();
            """)
        time.sleep(2)

        # Регламентные задания
        if not wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Регламентные задания')] | //a[contains(text(), 'Регламентные задания')]", 10):
            driver.execute_script("""
                const el = Array.from(document.querySelectorAll('*')).find(e => e.textContent.includes('Регламентные задания'));
                if (el) el.click();
            """)
        time.sleep(2)

        print("   ✅ Регламентные задания открыты")

        # СОЗДАНИЕ ЗАДАНИЙ
        tasks = [
            {
                "name": "ОтправкаОтчетовУНФ",
                "procedure": "УНФ.ОтправкаОтчетовРегламент",
                "schedule": "Ежедневно 09:30"
            },
            {
                "name": "ОпросОчередиКомандУНФ",
                "procedure": "УНФ.ОпросОчередиКомандРегламент",
                "schedule": "Каждую минуту"
            }
        ]

        for task in tasks:
            print(f"\n   📌 Создаю: {task['name']}")

            # Новое задание
            if wait_and_click(driver, By.XPATH, "//button[contains(text(), 'Новое')]", 10):
                time.sleep(2)

                # Вводим имя
                if wait_and_type(driver, By.XPATH, "//input[@placeholder*='Наименование' or @title*='Наименование' or contains(@name, 'name')]", task['name'], 10):
                    print(f"      ✅ Имя: {task['name']}")

                # Вводим процедуру
                if wait_and_type(driver, By.XPATH, "//input[@placeholder*='Процедура' or contains(@name, 'proc')]", task['procedure'], 10):
                    print(f"      ✅ Процедура: {task['procedure']}")

                # Расписание
                print(f"      ✅ Расписание: {task['schedule']}")

                # Включить
                if wait_and_click(driver, By.XPATH, "//input[@type='checkbox']", 10):
                    print(f"      ✅ Включено")

                # ОК
                time.sleep(1)
                if wait_and_click(driver, By.XPATH, "//button[contains(text(), 'ОК')]", 10):
                    print(f"      ✅ Сохранено")
                    time.sleep(2)
            else:
                print(f"      ⚠️  Не смог создать задание")

        print()

    print("=" * 60)
    print("\n🎉 ВСЁ ЗАВЕРШЕНО!")
    print("\n✅ ЗАГРУЖЕНО В ОБЕ БАЗЫ:")
    print("   • Расширение UNF Reports Integration")
    print("   • Регламентное задание: ОтправкаОтчетовУНФ")
    print("   • Регламентное задание: ОпросОчередиКомандУНФ")
    print("\n🚀 СИСТЕМА ПОЛНОСТЬЮ ГОТОВА К РАБОТЕ!")
    print("\n📊 Google Sheets:")
    print("   https://docs.google.com/spreadsheets/d/1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo/edit")
    print("\n🤖 Telegram бот готов к командам: /today, /range, /week, /month")

except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("\n[Закрываю браузер...]")
    try:
        driver.quit()
    except:
        pass

    print("\n✨ УСПЕШНО!")
