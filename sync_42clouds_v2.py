import logging
import os
import requests
import base64
from datetime import datetime
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

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


def get_report_data_http(base_url):
    """Получить данные отчёта через HTTP запрос"""
    logger.info(f"Getting report data from {base_url}")

    # Prepare auth
    auth = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        # Try to get the report page directly
        report_url = f"{base_url}e1cib/app/Report.Взаиморасчеты"
        logger.info(f"Fetching: {report_url}")

        response = requests.get(
            report_url,
            headers=headers,
            timeout=30,
            verify=False,
            allow_redirects=True
        )

        logger.info(f"Response status: {response.status_code}")

        if response.status_code != 200:
            logger.warning(f"Got {response.status_code}, trying alternative URL...")
            # Try alternative URL
            report_url = f"{base_url}e1cib/list/Report"
            response = requests.get(report_url, headers=headers, timeout=30, verify=False)
            logger.info(f"Alternative response: {response.status_code}")

        # Parse HTML to find the report table
        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for table
        tables = soup.find_all('table')
        logger.info(f"Found {len(tables)} tables in page")

        if not tables:
            logger.warning("No tables found in response")
            return None

        # Extract data from first substantial table
        data = []
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) > 3:  # Significant table
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        row_data = [cell.get_text(strip=True) for cell in cells]
                        if any(row_data):  # Skip empty rows
                            data.append(row_data)

                if data:
                    logger.info(f"Extracted {len(data)} rows from table")
                    return data

        return None

    except Exception as e:
        logger.error(f"Error fetching report: {e}")
        return None


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

    max_cols = max(len(row) for row in data) if data else 1
    end_col = chr(64 + max_cols)
    end_row = start_row + len(data) - 1
    cell_range = f"A{start_row}:{end_col}{end_row}"

    try:
        worksheet.update(data, cell_range)
        logger.info(f"Data inserted successfully: {len(data)} rows × {max_cols} cols into {cell_range}")
        return True
    except Exception as e:
        logger.error(f"Failed to insert data into {cell_range}: {e}")
        return False


def sync_all_bases():
    """Синхронизировать обе базы"""
    logger.info("Starting sync of all bases")

    for base_name, config in BASES.items():
        logger.info(f"Processing {base_name}...")

        data = get_report_data_http(config["url"])
        if data:
            insert_to_sheets(
                SPREADSHEET_ID,
                config["sheet_name"],
                config["range_name"],
                data,
                config["start_row"]
            )
        else:
            logger.warning(f"Failed to get data from {base_name}")

    logger.info("Sync completed")


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    sync_all_bases()
