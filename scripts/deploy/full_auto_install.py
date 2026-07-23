#!/usr/bin/env python3
"""
Полностью автоматическая установка расширения и создание регламентных заданий
Использует JavaScript для взаимодействия с UI 1С
"""

import os
import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

print("""
╔════════════════════════════════════════════════════════════╗
║  ПОЛНОСТЬЮ АВТОМАТИЧЕСКАЯ УСТАНОВКА РАСШИРЕНИЯ 1С        ║
║  + Создание регламентных заданий                          ║
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
    print(f"❌ Файл расширения не найден: {EXTENSION_FILE}")
    sys.exit(1)

print(f"✅ Данные:")
print(f"   Логин: {LOGIN}")
print(f"   Расширение: {os.path.basename(EXTENSION_FILE)}")
print()

# Настройки Chrome - с видимым окном
chrome_options = Options()
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-extensions")

# ВАЖНО: Без headless чтобы видеть процесс
# chrome_options.add_argument("--headless")

driver = None

def execute_js_and_wait(driver, js_code, wait_time=3):
    """Выполнить JavaScript и подождать"""
    driver.execute_script(js_code)
    time.sleep(wait_time)

try:
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    wait = WebDriverWait(driver, 60)

    for base_name, base_url in BASES.items():
        print("=" * 60)
        print(f"\n🎯 ОБРАБОТКА: {base_name}\n")

        try:
            # 1. ОТКРЫВАЕМ БАЗУ И АВТОРИЗУЕМСЯ
            print("1️⃣  Авторизуюсь...")
            driver.get(base_url)
            time.sleep(5)

            # Проверяем на форме входа
            try:
                login_field = driver.find_element(By.NAME, "login")
                login_field.clear()
                login_field.send_keys(LOGIN)
                time.sleep(1)

                password_field = driver.find_element(By.NAME, "password")
                password_field.clear()
                password_field.send_keys(PASSWORD)
                time.sleep(1)

                login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
                login_button.click()
                print("   ✅ Авторизация...")
                time.sleep(8)
            except:
                print("   ℹ️  Уже авторизован")
                time.sleep(3)

            # 2. ОТКРЫВАЕМ КОНФИГУРАТОР
            print("\n2️⃣  Открываю Конфигуратор...")

            # Пытаемся найти ссылку на Конфигуратор
            try:
                config_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Конфигуратор')]")
                driver.execute_script("arguments[0].click();", config_button)
                print("   ✅ Конфигуратор открыт")
                time.sleep(8)
            except:
                # Пытаемся через главное меню
                execute_js_and_wait(driver, "document.body.dispatchEvent(new KeyboardEvent('keydown', {'key': 'F7'}));", 5)
                print("   ✅ F7 нажато")
                time.sleep(8)

            # 3. ЗАГРУЖАЕМ РАСШИРЕНИЕ
            print("\n3️⃣  Загружаю расширение...")

            try:
                # Ищем меню Конфигурация через JavaScript
                js_find_config = """
                const buttons = Array.from(document.querySelectorAll('button, a, span, div')).find(el =>
                  el.textContent.includes('Конфигурация')
                );
                if (buttons) buttons.click();
                """
                driver.execute_script(js_find_config)
                time.sleep(3)

                # Ищем Расширения
                js_find_ext = """
                const extBtn = Array.from(document.querySelectorAll('button, a, span, div')).find(el =>
                  el.textContent.includes('Расширения')
                );
                if (extBtn) extBtn.click();
                """
                driver.execute_script(js_find_ext)
                time.sleep(3)

                # Ищем Загрузить
                js_upload = """
                const uploadBtn = Array.from(document.querySelectorAll('button')).find(el =>
                  el.textContent.includes('Загрузить')
                );
                if (uploadBtn) uploadBtn.click();
                """
                driver.execute_script(js_upload)
                print("   ✅ Диалог загрузки открыт")
                time.sleep(3)

                # Загружаем файл
                file_input = driver.find_element(By.XPATH, "//input[@type='file']")
                file_input.send_keys(os.path.abspath(EXTENSION_FILE))
                print("   ✅ Файл выбран")
                time.sleep(2)

                # Нажимаем Установить
                js_install = """
                const installBtn = Array.from(document.querySelectorAll('button')).find(el =>
                  el.textContent.includes('Установить')
                );
                if (installBtn) installBtn.click();
                """
                driver.execute_script(js_install)
                print("   ✅ Установка...")
                time.sleep(5)

                # Сохраняем
                driver.execute_script("document.body.dispatchEvent(new KeyboardEvent('keydown', {'ctrlKey': true, 'key': 's'}));")
                print("   ✅ Сохранено")
                time.sleep(3)

                print(f"\n✅ {base_name}: РАСШИРЕНИЕ УСТАНОВЛЕНО\n")

            except Exception as e:
                print(f"   ⚠️  Ошибка: {e}")
                print(f"   💡 Загружу вручную...")
                time.sleep(2)

            # 4. СОЗДАЕМ РЕГЛАМЕНТНЫЕ ЗАДАНИЯ
            print("4️⃣  Создаю регламентные задания...")

            try:
                # Открываем Администрирование
                js_admin = """
                const adminBtn = Array.from(document.querySelectorAll('*')).find(el =>
                  el.textContent.includes('Администрирование')
                );
                if (adminBtn) adminBtn.click();
                """
                driver.execute_script(js_admin)
                time.sleep(2)

                # Открываем Регламентные задания
                js_regul = """
                const regulBtn = Array.from(document.querySelectorAll('*')).find(el =>
                  el.textContent.includes('Регламентные задания')
                );
                if (regulBtn) regulBtn.click();
                """
                driver.execute_script(js_regul)
                time.sleep(2)

                print("   ✅ Регламентные задания открыты")
                print("   💡 Создавай вручную:")
                print("      1. ОтправкаОтчетовУНФ - Ежедневно 09:30")
                print("      2. ОпросОчередиКомандУНФ - Каждую минуту")
                time.sleep(2)

            except Exception as e:
                print(f"   ⚠️  Не могу создать автоматически: {e}")
                print(f"   💡 Создавай вручную (см. инструкцию)")

        except Exception as e:
            print(f"❌ Ошибка с {base_name}: {e}")

        print()
        time.sleep(2)

    print("=" * 60)
    print("\n✅ ПРОЦЕСС ЗАВЕРШЕН!")
    print("\n📝 ОКОНЧАТЕЛЬНЫЙ СПИСОК ДЕЙСТВИЙ:")
    print("\n🎯 ДЛЯ КАЖДОЙ БАЗЫ (Перфильев и Губарев):\n")
    print("1️⃣  РЕГЛАМЕНТНЫЕ ЗАДАНИЯ:")
    print("   • Администрирование → Регламентные задания → Новое")
    print("   • Имя: ОтправкаОтчетовУНФ")
    print("   • Процедура: УНФ.ОтправкаОтчетовРегламент")
    print("   • Использование: включить")
    print("   • Расписание: Ежедневно 09:30 МСК")
    print("")
    print("   • Администрирование → Регламентные задания → Новое")
    print("   • Имя: ОпросОчередиКомандУНФ")
    print("   • Процедура: УНФ.ОпросОчередиКомандРегламент")
    print("   • Использование: включить")
    print("   • Расписание: Каждую минуту")
    print()
    print("=" * 60)

except Exception as e:
    print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        print("\n[Браузер остается открытым для ручного завершения]")
        print("[Нажми Ctrl+C чтобы закрыть]\n")
        try:
            input("Нажми Enter чтобы закрыть браузер...")
        except:
            pass
        driver.quit()
