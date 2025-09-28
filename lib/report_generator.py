# lib/report_generator.py

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
    "Jayapura": ["JAYAPURA 1", "JAYAPURA 2"], "Abepura":  ["ABEPURA 1"],
    "Waena":    ["ABEPURA 2"], "Sentani":  ["SENTANI"], "Biak":     ["BIAK"],
    "Merauke":  ["MERAUKE"], "Wilsus":   ["WILSUS"]
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
        lines = text.split('\n')
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
                _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)
                current_chunk = line
            else:
                if current_chunk: current_chunk += "\n"
                current_chunk += line
        if current_chunk: _send_single_telegram_message(TELEGRAM_URL, chat_id, current_chunk)

def _send_single_telegram_message(url, chat_id, text, reply_to_message_id=None):
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if reply_to_message_id: payload['reply_to_message_id'] = reply_to_message_id
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_json = response.json()
        if not response_json.get("ok") and "replied not found" in response_json.get("description", ""):
            payload.pop('reply_to_message_id', None)
            response = requests.post(url, json=payload, timeout=10)
        if not response.json().get("ok"): print(f"TELEGRAM API ERROR: {response.json().get('description')}")
    except requests.exceptions.RequestException as e: print(f"NETWORK ERROR sending to Telegram: {e}")

def get_sheet_as_dataframe(spreadsheet_id, sheet_name):
    gc = get_gspread_client()
    if not gc: raise ConnectionError("Google Sheets client is not authorized.")
    sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    all_values = sheet.get_all_values()
    if not all_values: return pd.DataFrame()
    cleaned_headers = [clean_header(h) for h in all_values[0]]
    df = pd.DataFrame(all_values[1:], columns=cleaned_headers)
    return df

def clean_header(header_text):
    if not isinstance(header_text, str): return ""
    return re.sub(r'\s+', ' ', header_text.replace('\n', ' ')).strip().lower()

def generate_sqm_regional_report(group_name, sektor_values_to_filter):
    try:
        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        THRESHOLD_UMUR = int(os.environ.get("UMUR_THRESHOLD", "10"))
        df = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
        df_sektor = df[df['sektor'].str.strip().str.upper().isin(sektor_values_to_filter)]
        
        # Include tickets that are 'OPEN' AND have 'LOS' in 'Hasil Ukur'
        df_relevant = df_sektor[
            (df_sektor['status'].str.strip().str.upper() == 'OPEN') &
            (df_sektor['hasil ukur'].str.strip().str.upper() == 'LOS')
        ].copy()

        df_sqm = df_relevant[df_relevant['kategori loker'].str.strip().str.upper() == 'SQM'].copy()
        df_sqm['umur_numeric'] = pd.to_numeric(df_sqm['umur tiket'], errors='coerce')
        df_filtered = df_sqm[df_sqm['umur_numeric'] < THRESHOLD_UMUR]
        df_sorted = df_filtered.sort_values(by='umur_numeric', ascending=True)

        dt_str = datetime.now(pytz.timezone("Asia/Tokyo")).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM - {group_name} — {dt_str}\n"
        if df_sorted.empty: return (True, title + "\nTidak ada tiket SQM baru.")
        rows = []
        for _, row in df_sorted.iterrows():
            cust_type_map = {'PLATINUM': 'PLAT', 'DIAMOND': 'DMND', 'REGULER': 'REG'}
            cust_type = cust_type_map.get(str(row.get('customer type','')).upper(), row.get('customer type',''))
            status_sugar = 'NON SGR' if str(row.get('status sugar','')).strip().upper() == 'NON SUGAR' else row.get('status sugar','')
            status_fmt = f"<b>{status_sugar}</b>" if str(status_sugar).strip().upper() == 'SUGAR' else status_sugar
            data_str = " | ".join([f"<code>{row.get('incident','')}</code>", f"{row.get('umur tiket','')}j", cust_type, row.get('sto',''), status_fmt, row.get('hasil ukur','')])
            final_line = f"🔴 {data_str}" if str(status_sugar).strip().upper() == 'SUGAR' else data_str
            rows.append(final_line)
        return (True, title + "\n" + "\n".join(rows))
    except Exception as e:
        print(f"Error in generate_sqm_regional_report for {group_name}: {e}")
        return (False, f"Bot Error: Exception in SQM report for {group_name}.")

def generate_ccan_report():
    try:
        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        df_all = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
        
        # Include tickets that are 'OPEN' AND have 'LOS' in 'Hasil Ukur'
        df_relevant = df_all[
            (df_all['status'].str.strip().str.upper() == 'OPEN') &
            (df_all['hasil ukur'].str.strip().str.upper() == 'LOS')
        ].copy()

        df_ccan = df_relevant[df_relevant['kategori loker'].str.strip().str.upper() == 'SQM(CCAN)'].copy()
        df_insera_subset = get_sheet_as_dataframe(SPREADSHEET_ID, "INSERA")[['incident', 'customer segment']]
        df_merged = pd.merge(df_ccan, df_insera_subset, on='incident', how='left')
        df_merged['umur_numeric'] = pd.to_numeric(df_merged['umur tiket'], errors='coerce')
        df_sorted = df_merged.sort_values(by='umur_numeric', ascending=True)

        dt_str = datetime.now(pytz.timezone("Asia/Tokyo")).strftime('%d/%m/%Y %H:%M')
        title = f"⏰ Laporan Tiket SQM(CCAN) — {dt_str}\n"
        if df_sorted.empty: return (True, title + "\nTidak ada tiket SQM(CCAN) yang open.")
        rows = []
        for _, row in df_sorted.iterrows():
            segment = row.get('customer segment', 'N/A')
            if pd.isna(segment): segment = 'N/A'
            data_str = " | ".join([f"<code>{row.get('incident','')}</code>", f"{row.get('umur tiket','')}j", str(segment), row.get('sto',''), row.get('hasil ukur','')])
            rows.append(data_str)
        return (True, title + "\n" + "\n".join(rows))
    except Exception as e:
        print(f"Error in generate_ccan_global_report: {e}")
        return (False, "Bot Error: Exception in SQM(CCAN) report.")

# find_summary_in_insera is not actively used but can be left as is.
def find_summary_in_insera(incident_id):
    try:
        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
        gc = get_gspread_client()
        if not gc: return "Error: Could not connect to Google."
        sheet = gc.open_by_key(SPREADSHEET_ID).worksheet("INSERA")
        cell = sheet.find(incident_id, in_column=2)
        if cell:
            headers = sheet.row_values(1)
            try:
                summary_col = [h.upper() for h in headers].index("SUMMARY") + 1
                return sheet.cell(cell.row, summary_col).value
            except ValueError: return "Summary column not found."
        else: return None
    except Exception as e:
        print(f"Error finding summary in INSERA: {e}")
        return "Error during INSERA lookup."