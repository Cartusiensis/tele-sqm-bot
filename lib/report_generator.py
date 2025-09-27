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

def send_telegram_message(chat_id, text, reply_to_message_id=None):
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

def get_sheet_as_dataframe(spreadsheet_id, sheet_name):
    gc = get_gspread_client()
    if not gc:
        raise ConnectionError("Google Sheets client is not authorized.")
    spreadsheet = gc.open_by_key(spreadsheet_id)
    sheet = spreadsheet.worksheet(sheet_name)
    all_values = sheet.get_all_values()
    if not all_values:
        return pd.DataFrame()
    header_row = all_values[0]
    data_rows = all_values[1:]
    cleaned_headers = [clean_header(h) for h in header_row]
    df = pd.DataFrame(data_rows, columns=cleaned_headers)
    return df

def clean_header(header_text):
    if not isinstance(header_text, str): return ""
    cleaned_text = header_text.replace('\n', ' ')
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    return cleaned_text.strip().lower()

# --- NEW: Function for the Regional SQM Report ---
def generate_sqm_regional_report(group_name, sektor_values_to_filter):
    """Generates the classic formatted report for a specific Sektor group, filtered for 'SQM'."""
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    TIMEZONE = "Asia/Tokyo"
    THRESHOLD_UMUR = int(os.environ.get("UMUR_THRESHOLD", "10"))
    
    try:
        df = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
        
        # --- Filtering Logic for SQM Regional ---
        df_sektor_filtered = df[df['sektor'].str.strip().str.upper().isin(sektor_values_to_filter)]
        df_open = df_sektor_filtered[df_sektor_filtered['status'].str.strip().str.upper() == 'OPEN'].copy()
        # NEW filter by Kategori Loker
        df_sqm_only = df_open[df_open['kategori loker'].str.strip().str.upper() == 'SQM'].copy()
        
        df_sqm_only['umur_numeric'] = pd.to_numeric(df_sqm_only['umur tiket'], errors='coerce')
        df_filtered = df_sqm_only[df_sqm_only['umur_numeric'] < THRESHOLD_UMUR]
        df_sorted = df_filtered.sort_values(by='umur_numeric', ascending=True)

        tz = pytz.timezone(TIMEZONE)
        dt_str = datetime.now(tz).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM - {group_name} — {dt_str}\n"
        body = ""

        if df_sorted.empty:
            body = "Tidak ada tiket SQM baru."
        else:
            rows = []
            for _, row in df_sorted.iterrows():
                incident = row.get('incident', '')
                umur = row.get('umur tiket', '')
                original_status_sugar = row.get('status sugar', '')
                hasil_ukur = row.get('hasil ukur', '')
                original_cust_type = row.get('customer type', '')
                sto = row.get('sto', '')

                cust_type_map = {'PLATINUM': 'PLAT', 'DIAMOND': 'DMND', 'REGULER': 'REG'}
                cust_type = cust_type_map.get(str(original_cust_type).upper(), original_cust_type)
                status_sugar = 'NON SGR' if str(original_status_sugar).strip().upper() == 'NON SUGAR' else original_status_sugar
                status_sugar_formatted = f"<b>{status_sugar}</b>" if str(status_sugar).strip().upper() == 'SUGAR' else status_sugar
                
                data_string = " | ".join([f"<code>{incident}</code>", f"{umur}j", cust_type, sto, status_sugar_formatted, hasil_ukur])
                final_line = f"🔴 {data_string}" if str(status_sugar).strip().upper() == 'SUGAR' else data_string
                rows.append(final_line)
            
            body = "\n".join(rows)
        
        return (True, title + "\n" + body)

    except Exception as e:
        print(f"Error during SQM regional report generation for {group_name}: {e}")
        return (False, f"Bot Error: An exception occurred during SQM report generation for {group_name}.")

# --- Function for the SQM(CCAN) Report ---
def generate_ccan_report():
    """Generates a global report for all open 'SQM(CCAN)' tickets, enriched with data from INSERA."""
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    TIMEZONE = "Asia/Tokyo"
    
    try:
        # Step 1: Fetch data from both sheets
        df_all_tickets = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
        df_insera = get_sheet_as_dataframe(SPREADSHEET_ID, "INSERA")
        
        # Keep only the columns we need from INSERA for an efficient merge
        df_insera_subset = df_insera[['incident', 'customer segment']]

        # Step 2: Filter the main data for open SQM(CCAN) tickets
        df_open = df_all_tickets[df_all_tickets['status'].str.strip().str.upper() == 'OPEN'].copy()
        df_ccan_filtered = df_open[df_open['kategori loker'].str.strip().str.upper() == 'SQM(CCAN)'].copy()

        # Step 3: Merge the two dataframes to add the "customer segment"
        # 'how="left"' ensures we keep all CCAN tickets, even if they have no match in INSERA
        df_merged = pd.merge(df_ccan_filtered, df_insera_subset, on='incident', how='left')
        
        # Sort by umur tiket (must convert to numeric first)
        df_merged['umur_numeric'] = pd.to_numeric(df_merged['umur tiket'], errors='coerce')
        df_sorted = df_merged.sort_values(by='umur_numeric', ascending=True)

        # Step 4: Format the report text
        tz = pytz.timezone(TIMEZONE)
        dt_str = datetime.now(tz).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM(CCAN) — {dt_str}\n"
        body = ""

        if df_sorted.empty:
            body = "Tidak ada tiket SQM(CCAN) yang open."
        else:
            rows = []
            for _, row in df_sorted.iterrows():
                incident = row.get('incident', '')
                umur = row.get('umur tiket', '')
                segment = row.get('customer segment', '')
                # Handle cases where there was no match in INSERA (value will be NaN)
                if pd.isna(segment):
                    segment = 'N/A'
                sto = row.get('sto', '')
                hasil_ukur = row.get('hasil ukur', '')

                data_string = " | ".join([f"<code>{incident}</code>", f"{umur}j", str(segment), sto, hasil_ukur])
                rows.append(data_string)

            body = "\n".join(rows)

        return (True, title + "\n" + body)

    except Exception as e:
        print(f"Error during SQM(CCAN) global report generation: {e}")
        return (False, "Bot Error: An exception occurred during SQM(CCAN) report generation.")


# --- find_summary_in_insera (Unchanged) ---
def find_summary_in_insera(incident_id):
    # This function remains unchanged.
    try:
        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        gc = get_gspread_client()
        if not gc: return "Error: Could not connect to Google."
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        insera_sheet = spreadsheet.worksheet("INSERA")
        cell = insera_sheet.find(incident_id, in_column=2)
        if cell:
            headers = insera_sheet.row_values(1)
            try:
                summary_col_index = [h.upper() for h in headers].index("SUMMARY") + 1
                summary_value = insera_sheet.cell(cell.row, summary_col_index).value
                return summary_value
            except ValueError: return "Summary column not found."
        else: return None
    except Exception as e:
        print(f"Error finding summary in INSERA: {e}")
        return f"Error during INSERA lookup."