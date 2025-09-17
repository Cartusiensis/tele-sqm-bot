import os
import json
import requests
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz
import re

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
    """
    Sends a message to Telegram, automatically splitting it into chunks
    if it exceeds the 4096 character limit.
    """
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set!")
        return

    TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    MAX_LENGTH = 4096

    # --- NEW: Chunking Logic ---
    if len(text) <= MAX_LENGTH:
        # If the message is short enough, send it in one go.
        _send_single_telegram_message(TELEGRAM_URL, chat_id, text, reply_to_message_id)
    else:
        # If the message is too long, split it into chunks.
        print(f"Message is too long ({len(text)} chars). Splitting into chunks.")
        
        # Split the message by newline characters to keep lines intact.
        lines = text.split('\n')
        current_chunk = ""
        
        for line in lines:
            # Check if adding the next line would exceed the limit.
            # The +1 is for the newline character we'll add back.
            if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
                # If it would, send the chunk we have so far.
                _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)
                # And start a new chunk with the current line.
                current_chunk = line
            else:
                # Otherwise, add the line to the current chunk.
                if current_chunk: # Add a newline if it's not the first line
                    current_chunk += "\n"
                current_chunk += line
        
        # After the loop, send any remaining part of the message.
        if current_chunk:
            _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)

def _send_single_telegram_message(url, chat_id, text, reply_to_message_id=None):
    """Internal helper function to send one message and log the response."""
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML"
    }
    
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_json = response.json()
        print(f"Telegram API response for chat_id {chat_id}: {response_json}")
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
def generate_report_text():
    """
    Fetches data from Google Sheets and returns the formatted report as a string.
    Returns a tuple: (success: bool, report_text: str)
    """
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    SHEET_NAME = "SQM"
    TIMEZONE = "Asia/Tokyo"
    THRESHOLD_UMUR = int(os.environ.get("UMUR_THRESHOLD", "12"))

    gc = get_gspread_client()
    if not gc:
        return (False, "Bot Error: Could not authorize with Google Sheets.")

    try:
        df = get_sheet_as_dataframe(SPREADSHEET_ID, SHEET_NAME)

        # --- Filtering and Sorting Logic (same as before) ---
        required_cols = ['status', 'umur tiket', 'incident']
        for col in required_cols:
            if col not in df.columns:
                return (False, f"Error: Column '{col}' not found in spreadsheet.")

        df_open = df[df['status'].str.strip().str.upper() == 'OPEN'].copy()
        df_open['umur_numeric'] = pd.to_numeric(df_open['umur tiket'], errors='coerce')
        df_filtered = df_open[df_open['umur_numeric'] < THRESHOLD_UMUR]
        df_sorted = df_filtered.sort_values(by='umur_numeric', ascending=True)

        # --- Formatting the Message ---
        tz = pytz.timezone(TIMEZONE)
        dt_str = datetime.now(tz).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM — {dt_str}\n"

        body = ""

        if df_sorted.empty:
            body = "Tidak ada tiket yang memenuhi kriteria."
        else:
            rows = []
            for _, row in df_sorted.iterrows():
                # 1. Get and transform data (no changes here)
                incident = row.get('incident', '')
                umur = row.get('umur tiket', '')
                original_status_sugar = row.get('status sugar', 'N/A')
                hasil_ukur = row.get('hasil ukur', 'N/A')
                original_cust_type = row.get('customer type', '')
                sto = row.get('sto', '')

                cust_type_map = {'PLATINUM': 'PLAT', 'DIAMOND': 'DMND', 'REGULER': 'REG'}
                cust_type = cust_type_map.get(original_cust_type.upper(), original_cust_type)
                status_sugar = 'NON SGR' if original_status_sugar.strip().upper() == 'NON SUGAR' else original_status_sugar

                # 2. Prepare the status text (bold if 'Sugar')
                status_sugar_formatted = f"<b>{status_sugar}</b>" if status_sugar.strip().upper() == 'SUGAR' else status_sugar

                # 3. Build the main data string with the " | " separator
                # Order: INC | Umur | Cust Type | STO | Status Sugar | Hasil Ukur
                data_string = " | ".join([
                    f"<code>{incident}</code>",
                    f"{umur}j",
                    cust_type,
                    sto,
                    status_sugar_formatted, # Use the potentially bolded version
                    hasil_ukur
                ])

                # 4. Conditionally prepend the emoji to the final line
                if status_sugar.strip().upper() == 'SUGAR':
                    # Emoji comes first, then the data string, with no separator
                    final_line = f"🔴 {data_string}"
                else:
                    # For normal tickets, the line is just the data string
                    final_line = data_string
                
                rows.append(final_line)
            
            # The body is now the joined rows
            body = "\n".join(rows)

        final_message = title + "\n" + body

        return (True, final_message)

    except Exception as e:
        print(f"Error during report generation: {e}")
        return (False, f"Bot Error: An exception occurred during report generation: {e}")


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