import logging
import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Configure file logging
log_file = os.path.join(os.path.dirname(__file__), "sync_42clouds.log")
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG)

# Credentials
LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

BASES = {
    "gubarev": {
        "url": "https://base.42clouds.com/unf/64904/",
        "sheet_name": "ДАННЫЕ_Губарев",
        "range_name": "Взаиморасчёты по Губарев",
        "start_row": 4
    },
    "perfilev": {
        "url": "https://base.42clouds.com/unf/152757/",
        "sheet_name": "ДАННЫЕ_Перфильев",
        "range_name": "Взаиморасчёты по ИП Перфильев",
        "start_row": 4
    }
}

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")


def login_to_42clouds(driver, base_url):
    """Логиниться в 42clouds"""
    logger.info(f"Logging into {base_url}")
    driver.get(base_url)
    time.sleep(3)

    wait = WebDriverWait(driver, 30)

    try:
        # Ждём пока JavaScript загрузит форму логина
        logger.info("Waiting for login form...")

        # Пробуем разные селекторы
        login_field = None
        for selector in [(By.NAME, "login"), (By.ID, "login"), (By.CSS_SELECTOR, "input[type='text']")]:
            try:
                login_field = wait.until(EC.presence_of_element_located(selector))
                logger.info(f"Found login field with {selector}")
                break
            except:
                continue

        if not login_field:
            logger.error("Could not find login field")
            return False

        time.sleep(1)
        login_field.clear()
        login_field.send_keys(LOGIN)
        logger.info("Login entered")

        # Введём пароль
        password_field = driver.find_element(By.NAME, "password")
        password_field.clear()
        password_field.send_keys(PASSWORD)
        logger.info("Password entered")

        # Нажмём кнопку входа
        login_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Вход')] | //button[contains(text(), 'Войти')]")
        login_button.click()
        logger.info("Login button clicked")

        # Ждём загрузки главной страницы
        wait.until(EC.url_changes(base_url))
        time.sleep(2)
        logger.info("Login successful")
        return True
    except Exception as e:
        logger.error(f"Login failed: {e}")
        logger.error(f"Current URL: {driver.current_url}")
        return False


def get_report_data(base_url, report_name="Взаиморасчеты"):
    """Получить данные из отчёта"""
    logger.info(f"Getting report data from {base_url}")

    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        if not login_to_42clouds(driver, base_url):
            return None

        logger.info("Opening reports page...")
        # Переходим на страницу отчётов
        driver.get(f"{base_url}e1cib/list/Report")
        time.sleep(3)
        wait = WebDriverWait(driver, 15)

        # Ищем отчёт "Взаиморасчёты (кратко)" или похожий
        try:
            # Пробуем разные варианты названия
            report_xpath = f"//a[contains(text(), '{report_name}')]"
            logger.info(f"Looking for report with xpath: {report_xpath}")

            report_link = wait.until(
                EC.element_to_be_clickable((By.XPATH, report_xpath))
            )
            logger.info(f"Found report link: {report_link.text}")
            report_link.click()

            # Ждём загрузки таблицы
            logger.info("Waiting for report table to load...")
            time.sleep(5)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

            # Парсим таблицу
            table = driver.find_element(By.TAG_NAME, "table")
            rows = table.find_elements(By.TAG_NAME, "tr")

            data = []
            for i, row in enumerate(rows):
                cells = row.find_elements(By.TAG_NAME, "td")
                if cells:
                    row_data = [cell.text.strip() for cell in cells]
                    if any(row_data):  # Skip empty rows
                        data.append(row_data)
                        if i < 3:  # Log first few rows
                            logger.info(f"Row {i}: {row_data[:3]}")

            logger.info(f"Extracted {len(data)} rows from report")
            return data if data else None

        except Exception as e:
            logger.error(f"Failed to find or open report: {e}")
            logger.error(f"Page source preview: {driver.page_source[:500]}")
            return None

    except Exception as e:
        logger.error(f"General error in get_report_data: {e}")
        return None
    finally:
        try:
            driver.quit()
        except:
            pass


def insert_to_sheets(spreadsheet_id, sheet_name, range_name, data, start_row=4):
    """Вставить данные в Google Sheets"""
    if not data:
        logger.warning("No data to insert")
        return False

    logger.info(f"Inserting {len(data)} rows into {sheet_name}")

    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except Exception as e:
        logger.error(f"Failed to authenticate with Google Sheets: {e}")
        return False

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        logger.info(f"Found worksheet: {sheet_name}")
    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"Worksheet '{sheet_name}' not found. Available sheets: {[w.title for w in spreadsheet.worksheets()]}")
        return False

    # Вставляем данные начиная со строки start_row (строки в гугле 1-indexed)
    max_cols = max(len(row) for row in data) if data else 1
    end_col = chr(64 + max_cols)
    end_row = start_row + len(data) - 1
    cell_range = f"A{start_row}:{end_col}{end_row}"

    try:
        worksheet.update(cell_range, data)
        logger.info(f"Data inserted successfully: {len(data)} rows × {max_cols} cols into {cell_range}")
        return True
    except Exception as e:
        logger.error(f"Failed to insert data into {cell_range}: {e}")
        return False


def sync_all_bases():
    """Синхронизировать обе базы"""
    logger.info("Starting sync of all bases")
    results = {}

    for base_name, config in BASES.items():
        logger.info(f"Processing {base_name}...")

        data = get_report_data(config["url"])
        if data:
            success = insert_to_sheets(
                SPREADSHEET_ID,
                config["sheet_name"],
                config["range_name"],
                data,
                config["start_row"]
            )
            results[base_name] = "success" if success else "insert_failed"
            logger.info(f"{base_name}: {'✅ OK' if success else '❌ Failed'}")
        else:
            logger.warning(f"Failed to get data from {base_name}")
            results[base_name] = "no_data"

    logger.info(f"Sync completed. Results: {results}")
    return results


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    sync_all_bases()
