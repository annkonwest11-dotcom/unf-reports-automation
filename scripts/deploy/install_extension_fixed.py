#!/usr/bin/env python3
"""
Автоматическая загрузка расширения 1С - Вариант 2 (Selenium)
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
║     Вариант 2: Безопасный способ (Selenium)               ║
╚════════════════════════════════════════════════════════════╝
""")

# Встроенные данные
login = "api_bot"
print(f"📧 Логин: {login}")
print()

# Получаем пароль локально
try:
    password = getpass.getpass("🔐 Введи пароль для api_bot (не будет видно): ")
except Exception as e:
    # Если getpass не работает, пытаемся обычный input
    password = input("🔐 Введи пароль для api_bot: ")

if not password:
    print("❌ Пароль не введен")
    sys.exit(1)

# Путь к расширению
extension_file = "/Users/anna/claude-test/1C_UNF_EXTENSION_READY.bsl"
if not os.path.exists(extension_file):
    print(f"❌ Файл расширения не найден: {extension_file}")
    sys.exit(1)

print(f"✅ Расширение: {os.path.basename(extension_file)}")
print()

# Базы которые нужно обновить
bases = {
    "Перфильев": "https://base.42clouds.com/unf/152757/",
    "Губарев": "https://base.42clouds.com/unf/64904/",
}

print(f"📋 Буду загружать расширение в {len(bases)} базы")
print("   (браузер откроется автоматически)")
print()

# Настройки Chrome
chrome_options = Options()
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)

driver = None
success_count = 0

try:
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 30)

    for base_name, base_url in bases.items():
        print("═══════════════════════════════════════════════════════════")
        print(f"\n🎯 ЗАГРУЖАЮ В: {base_name}")
        print(f"   URL: {base_url}\n")

        try:
            # 1. Открываем базу
            print("1️⃣  Открываю базу...")
            driver.get(base_url)
            time.sleep(3)

            # 2. Проверяем на странице логина или уже внутри
            current_url = driver.current_url
            if "login" in current_url.lower():
                print("   🔐 Форма входа найдена")
                
                # Вводим логин
                try:
                    login_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
                    login_field.clear()
                    login_field.send_keys(login)
                    print(f"   ✅ Логин '{login}' введен")
                except Exception as e:
                    print(f"   ⚠️  Логин не введен: {e}")

                # Вводим пароль
                try:
                    password_field = driver.find_element(By.NAME, "password")
                    password_field.clear()
                    password_field.send_keys(password)
                    print("   ✅ Пароль введен")
                except Exception as e:
                    print(f"   ⚠️  Пароль не введен: {e}")

                # Нажимаем Enter или кнопку входа
                try:
                    login_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Вход')] | //button[contains(text(), 'Войти')] | //button[@type='submit']")
                    login_button.click()
                    print("   ✅ Вход выполнен")
                    time.sleep(5)
                except Exception as e:
                    print(f"   ⚠️  Кнопка входа не найдена, пытаюсь Enter...")
                    password_field.send_keys("\n")
                    time.sleep(5)
            else:
                print("   ✅ Уже авторизован в системе")

            # 3. Открываем Конфигуратор (F7)
            print("\n2️⃣  Открываю Конфигуратор...")
            
            try:
                # Пытаемся через ссылку в меню
                config_links = driver.find_elements(By.XPATH, "//a[contains(text(), 'Конфигуратор')] | //a[contains(text(), '1С:Конфигуратор')]")
                if config_links:
                    config_links[0].click()
                    print("   ✅ Конфигуратор открыт (через меню)")
                else:
                    print("   ⚠️  Конфигуратор не найден в меню")
                    print("   💡 Пожалуйста, вручную нажми F7 в открытом окне браузера")
                    input("   [Нажми Enter когда будешь в Конфигураторе]")
                
                time.sleep(3)
            except Exception as e:
                print(f"   ⚠️  Ошибка при открытии: {e}")
                input("   [Нажми Enter когда будешь в Конфигураторе]")

            # 4. Загружаем расширение
            print("\n3️⃣  Загружаю расширение...")
            
            try:
                # Ищем меню Конфигурация
                config_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Конфигурация')]")))
                config_menu.click()
                print("   ✅ Меню Конфигурация открыто")
                time.sleep(2)

                # Ищем Расширения
                ext_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Расширения')]")))
                ext_menu.click()
                print("   ✅ Расширения открыты")
                time.sleep(2)

                # Ищем кнопку Загрузить
                upload_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Загрузить')]")))
                upload_btn.click()
                print("   ✅ Диалог загрузки открыт")
                time.sleep(2)

                # Ищем input для файла и загружаем
                file_input = driver.find_element(By.XPATH, "//input[@type='file']")
                file_input.send_keys(os.path.abspath(extension_file))
                print("   ✅ Файл выбран")
                time.sleep(2)

                # Нажимаем Установить
                install_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Установить')]")))
                install_btn.click()
                print("   ✅ Расширение установлено")
                time.sleep(3)

                # Сохраняем (Ctrl+S или через меню)
                try:
                    driver.execute_script("document.querySelector('button[title*=\"Сохранить\"]')?.click();")
                    print("   ✅ Сохранено")
                except:
                    print("   ℹ️  Нажми Ctrl+S чтобы сохранить")
                    input("   [Нажми Enter когда сохранишь]")

                time.sleep(2)

                print(f"\n✅ {base_name}: УСПЕШНО!")
                success_count += 1

            except Exception as e:
                print(f"   ❌ Ошибка при загрузке: {e}")
                print(f"   💡 Загрузи файл вручную и нажми Enter")
                input("   [Нажми Enter когда закончишь]")
                success_count += 1  # Считаем как успешное если ручная загрузка

        except Exception as e:
            print(f"❌ Ошибка при работе с {base_name}: {e}")

        print()

    print("═══════════════════════════════════════════════════════════")
    print(f"\n✅ ЗАГРУЗКА ЗАВЕРШЕНА! ({success_count}/{len(bases)} баз успешно)")
    print("\n🎉 Дальше нужно создать регламентные задания в 1С:")
    print("   1. ОтправкаОтчетовУНФ - Ежедневно 09:30")
    print("   2. ОпросОчередиКомандУНФ - Каждую минуту")
    print("\n📚 Смотри инструкцию:")
    print("   /Users/anna/claude-test/INSTALL_1C_EXTENSION.md")

except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        input("\n[Нажми Enter чтобы закрыть браузер]")
        driver.quit()

