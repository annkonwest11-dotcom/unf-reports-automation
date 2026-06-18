#!/usr/bin/env python3
"""
Автоматическая загрузка расширения 1С в облачные базы
Вариант 2: Безопасный способ с локальным вводом пароля
"""

import os
import sys
import getpass
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

print("""
╔════════════════════════════════════════════════════════════╗
║     Загрузка расширения 1С в облачные базы                ║
║     Вариант 2: Безопасный способ                          ║
╚════════════════════════════════════════════════════════════╝
""")

# Получаем логин
login = input("📧 Введи email для 42clouds: ").strip()
if not login:
    print("❌ Email не введен")
    sys.exit(1)

# Получаем пароль локально (не передается мне)
password = getpass.getpass("🔐 Введи пароль (он не будет видно): ")
if not password:
    print("❌ Пароль не введен")
    sys.exit(1)

# Путь к расширению
extension_file = "/Users/anna/claude-test/1C_UNF_EXTENSION_READY.bsl"
if not os.path.exists(extension_file):
    print(f"❌ Файл расширения не найден: {extension_file}")
    sys.exit(1)

print("\n✅ Данные получены")
print(f"   Логин: {login}")
print(f"   Расширение: {extension_file}")

# Базы которые нужно обновить
bases = {
    "Перфильев": "https://base.42clouds.com/unf/152757/",
    "Губарев": "https://base.42clouds.com/unf/64904/",
}

print(f"\n📋 Буду загружать расширение в {len(bases)} базы")
print()

# Настройки Chrome
chrome_options = Options()
# chrome_options.add_argument("--headless")  # Закомментировано чтобы видеть процесс
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)

driver = None

try:
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 30)

    for base_name, base_url in bases.items():
        print(f"═══════════════════════════════════════════════════════════")
        print(f"\n1️⃣  ЗАГРУЖАЮ В: {base_name}")
        print(f"    URL: {base_url}\n")

        try:
            # 1. Открываем базу
            print("🔐 Авторизуюсь...")
            driver.get(base_url)
            time.sleep(3)

            # 2. Вводим логин
            try:
                login_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
                login_field.clear()
                login_field.send_keys(login)
                print("   ✅ Логин введен")
            except:
                print("   ⚠️  Логин не нужен (может быть уже авторизован)")

            # 3. Вводим пароль
            try:
                password_field = driver.find_element(By.NAME, "password")
                password_field.clear()
                password_field.send_keys(password)
                print("   ✅ Пароль введен")
            except:
                pass

            # 4. Нажимаем кнопку входа
            try:
                login_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Вход')] | //button[contains(text(), 'Войти')]")
                login_button.click()
                print("   ✅ Вход выполнен")
                time.sleep(5)
            except:
                print("   ℹ️  Кнопка входа не найдена")

            # 5. Открываем Конфигуратор (F7 или меню)
            print("\n📂 Открываю Конфигуратор...")
            try:
                # Пытаемся через меню
                config_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Конфигуратор')] | //a[contains(text(), '1С:Конфигуратор')]")))
                config_link.click()
                time.sleep(3)
                print("   ✅ Конфигуратор открыт")
            except Exception as e:
                print(f"   ❌ Ошибка открытия Конфигуратора: {e}")
                continue

            # 6. Загружаем расширение
            print("\n📦 Загружаю расширение...")
            try:
                # Ищем меню Конфигурация
                config_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Конфигурация')]")))
                config_menu.click()
                time.sleep(2)

                # Ищем Расширения
                ext_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Расширения')]")))
                ext_menu.click()
                time.sleep(2)

                # Ищем кнопку Загрузить
                upload_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Загрузить')]")))
                upload_btn.click()
                time.sleep(2)

                # Ищем input для файла
                file_input = driver.find_element(By.XPATH, "//input[@type='file']")
                file_input.send_keys(os.path.abspath(extension_file))
                print("   ✅ Файл выбран")
                time.sleep(2)

                # Нажимаем Установить
                install_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Установить')]")))
                install_btn.click()
                print("   ✅ Расширение установлено")
                time.sleep(3)

                # Сохраняем Ctrl+S
                driver.execute_script("document.body.dispatchEvent(new KeyboardEvent('keydown', {'key': 's', 'ctrlKey': true}));")
                print("   ✅ Сохранено")
                time.sleep(2)

                print(f"\n✅ {base_name}: УСПЕШНО!")

            except Exception as e:
                print(f"   ❌ Ошибка при загрузке: {e}")
                continue

        except Exception as e:
            print(f"❌ Ошибка при работе с {base_name}: {e}")
            continue

        print()

    print("═══════════════════════════════════════════════════════════")
    print("\n✅ ЗАГРУЗКА ЗАВЕРШЕНА!")
    print("\n🎉 Теперь создай регламентные задания в 1С:")
    print("   1. ОтправкаОтчетовУНФ - Ежедневно 09:30")
    print("   2. ОпросОчередиКомандУНФ - Каждую минуту")
    print("\nСмотри инструкцию: /Users/anna/claude-test/INSTALL_1C_EXTENSION.md")

except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        input("\n[Нажми Enter чтобы закрыть браузер]")
        driver.quit()

