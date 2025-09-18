import os
import json
import requests
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
import re

SEKTOR_GROUPS = {
    "Jayapura": ["JAYAPURA 1", "JAYAPURA 2"],
    "Abepura":  ["ABEPURA 1"],
    "Waena":    ["ABEPURA 2"],
    "Sentani":  ["SENTANI"],
    "Biak":     ["BIAK"],
    "Merauke":  ["MERAUKE"],
    "Wilsus":   ["WILSUS"]
}

# --- Reusable function to get an authorized gspread client ---
def get_gspread_client():
    try:
        creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        creds_info = json.loads(creds_json_str)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Error loading Google credentials: {e}")
        return None

# --- Reusable function to send a message ---
def send_telegram_message(chat_id, text, reply_to_message_id=None):
    """Sends a message, automatically handling chunking for long messages."""
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set!")
        return
    TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    MAX_LENGTH = 4096

    if len(text) <= MAX_LENGTH:
        _send_single_telegram_message(TELEGRAM_URL, chat_id, text, reply_to_message_id)
    else:
        print(f"Message is too long ({len(text)} chars). Splitting into chunks.")
        lines = text.split('\n')
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
                _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)
                current_chunk = line
            else:
                if current_chunk: current_chunk += "\n"
                current_chunk += line
        if current_chunk:
            _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)

def _send_single_telegram_message(url, chat_id, text, reply_to_message_id=None):
    """Internal helper to send one message with a reply fallback."""
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_json = response.json()
        
        if not response_json.get("ok") and "message to be replied not found" in response_json.get("description", ""):
            print("Original message not found for replying. Sending as a normal message.")
            payload.pop('reply_to_message_id', None)
            response = requests.post(url, json=payload, timeout=10)
            response_json = response.json()

        print(f"Final Telegram API response for chat_id {chat_id}: {response_json}")
        if not response_json.get("ok"):
            print(f"TELEGRAM API ERROR: {response_json.get('description')}")
    except requests.exceptions.RequestException as e:
        print(f"NETWORK ERROR sending to Telegram: {e}")

# --- Function for reading data ---
def get_sheet_as_dataframe(spreadsheet_id, sheet_name):
    """
    Reads the entire sheet into a powerful pandas DataFrame and
    cleans the column headers to handle newlines and extra spaces.
    """
    gc = get_gspread_client()
    if not gc:
        raise ConnectionError("Google Sheets client is not authorized.")
    spreadsheet = gc.open_by_key(spreadsheet_id)
    sheet = spreadsheet.worksheet(sheet_name)
    
    # Get all data including the header row
    all_values = sheet.get_all_values()
    
    if not all_values:
        # Return an empty DataFrame if the sheet is empty
        return pd.DataFrame()

    # The first row is the header
    header_row = all_values[0]
    # The rest of the rows are the data
    data_rows = all_values[1:]
    
    cleaned_headers = [clean_header(h) for h in header_row]
    
    # Create the DataFrame with the cleaned headers
    df = pd.DataFrame(data_rows, columns=cleaned_headers)
    
    return df

def clean_header(header_text):
    """
    Cleans up a spreadsheet column header by making it lowercase
    and replacing newlines/multiple spaces with a single space.
    e.g., "Contact\nName" becomes "contact name".
    """
    if not isinstance(header_text, str):
        return ""
    # Replace any newline characters with a space
    cleaned_text = header_text.replace('\n', ' ')
    # Replace multiple whitespace characters with a single space
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    # Convert to lowercase and remove leading/trailing spaces
    return cleaned_text.strip().lower()

# --- The Core Report Generation Logic ---
def generate_report_text(group_name, sektor_values_to_filter):
    """Generates a formatted report string for a specific Sektor group."""
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    TIMEZONE = "Asia/Tokyo"
    THRESHOLD_UMUR = int(os.environ.get("UMUR_THRESHOLD", "10"))
    
    try:
        df = get_sheet_as_dataframe(SPREADSHEET_ID, "SQM")
        df_sektor_filtered = df[df['sektor'].str.strip().str.upper().isin(sektor_values_to_filter)]
        df_open = df_sektor_filtered[df_sektor_filtered['status'].str.strip().str.upper() == 'OPEN'].copy()
        df_open['umur_numeric'] = pd.to_numeric(df_open['umur tiket'], errors='coerce')
        df_filtered = df_open[df_open['umur_numeric'] < THRESHOLD_UMUR]
        df_sorted = df_filtered.sort_values(by='umur_numeric', ascending=True)

        tz = pytz.timezone(TIMEZONE)
        dt_str = datetime.now(tz).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM - {group_name} — {dt_str}\n"
        body = ""

        if df_sorted.empty:
            body = "Tidak ada tiket yang memenuhi kriteria."
        else:
            rows = []
            for _, row in df_sorted.iterrows():
                # Get and transform data
                incident = row.get('incident', '')
                umur = row.get('umur tiket', '')
                original_status_sugar = row.get('status sugar', '')
                hasil_ukur = row.get('hasil ukur', '')
                original_cust_type = row.get('customer type', '')
                sto = row.get('sto', '')

                cust_type_map = {'PLATINUM': 'PLAT', 'DIAMOND': 'DMND', 'REGULER': 'REG'}
                cust_type = cust_type_map.get(original_cust_type.upper(), original_cust_type)
                status_sugar = 'NON SGR' if original_status_sugar.strip().upper() == 'NON SUGAR' else original_status_sugar
                status_sugar_formatted = f"<b>{status_sugar}</b>" if status_sugar.strip().upper() == 'SUGAR' else status_sugar
                
                data_string = " | ".join([f"<code>{incident}</code>", f"{umur}j", cust_type, sto, status_sugar_formatted, hasil_ukur])
                final_line = f"🔴 {data_string}" if status_sugar.strip().upper() == 'SUGAR' else data_string
                rows.append(final_line)
            
            body = "\n".join(rows)
        
        return (True, title + "\n" + body)

    except Exception as e:
        print(f"Error during report generation for {group_name}: {e}")
        return (False, f"Bot Error: An exception occurred during report generation for {group_name}.")



def find_summary_in_insera(incident_id):
    """
    Performs a targeted search in the INSERA sheet to find the summary for a specific incident.
    Returns the summary text or None if not found.
    """
    try:
        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        gc = get_gspread_client()
        if not gc:
            return "Error: Could not connect to Google."

        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        insera_sheet = spreadsheet.worksheet("INSERA")
        
        # gspread's find() is perfect for a quick, targeted search.
        # It's slower than getting all records, but safer if headers are bad.
        cell = insera_sheet.find(incident_id, in_column=2)
        
        if cell:
            # Now we need to find the "SUMMARY" column.
            # Let's get the header row to find its index.
            headers = insera_sheet.row_values(1)
            try:
                # Find the column index for "SUMMARY" (case-insensitive)
                summary_col_index = [h.upper() for h in headers].index("SUMMARY") + 1
                # Get the summary value from the same row, but in the summary column
                summary_value = insera_sheet.cell(cell.row, summary_col_index).value
                return summary_value
            except ValueError:
                return "Summary column not found." # The column 'SUMMARY' doesn't exist
        else:
            return None # Incident not found in INSERA sheet
    except Exception as e:
        print(f"Error finding summary in INSERA: {e}")
        return f"Error during INSERA lookup."