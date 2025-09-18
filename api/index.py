import os
import json
import re
from http.server import BaseHTTPRequestHandler
import pandas as pd

# Import reusable functions
from lib.report_generator import (
    generate_report_text,
    get_sheet_as_dataframe,
    send_telegram_message,
    find_summary_in_insera,
    SEKTOR_GROUPS
)

def format_incident_details(incident_data):
    # ... (this function does not need to change)
    def esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    lines = [f"📄 Detail Ticket: <code>{esc(incident_data.get('incident', 'N/A'))}</code>"]
    field_map = {
        '• Contact Name': 'contact name', 
        '• No HP': 'no hp', 
        '• User': 'user',
        '• Customer Type': 'customer type', 
        '• DATEK': 'datek', '• STO': 'sto',
        '• Status Sugar': 'status sugar',
        '• Hasil Ukur': 'hasil ukur',
        '• Proses TTR 4 Jam': 'proses ttr 4 jam', 
        '• SN': 'sn',
        '• Summary': 'summary'
    }
    for label, col_name in field_map.items():
        if col_name in incident_data and pd.notna(incident_data[col_name]) and incident_data[col_name] != '':
            lines.append(f"{label}: {esc(incident_data[col_name])}")
    return "\n".join(lines)


# --- VERCEL'S MAIN HANDLER ---
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            update = json.loads(post_data)
            print(f"RECEIVED UPDATE: {json.dumps(update, indent=2)}")

            message = update.get("message") or update.get("edited_message")
            if not message:
                print("Update is not a standard message. Ignoring."); self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return

            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            text = message.get("text", "").strip()
            message_id = message.get("message_id")

            if not all([chat_id, user_id, text, message_id]):
                print("Incomplete message data. Ignoring."); self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return

            all_authorized_ids_str = os.environ.get("MY_CHAT_ID", "")
            all_authorized_ids = [int(i) for i in all_authorized_ids_str.split(',') if i]
            authorized_user_ids = [uid for uid in all_authorized_ids if uid > 0]
            authorized_group_ids = [gid for gid in all_authorized_ids if gid < 0]

            has_permission = (chat_id in authorized_group_ids) or (chat_id > 0 and user_id in authorized_user_ids)
            if not has_permission:
                print(f"Unauthorized access by user {user_id} in chat {chat_id}.")
                send_telegram_message(chat_id, "⛔️ Bot hanya dapat digunakan di grup, hubungi owner untuk mendapatkan akses pribadi.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            
            # --- PROCESS COMMANDS ---
            if text.lower().startswith("/sqm"):
                command_part = text.lower().split('@')[0][4:]
                found_group = False
                for group_name, sektor_list in SEKTOR_GROUPS.items():
                    if command_part == group_name.lower():
                        print(f"MATCHED COMMAND: /sqm{command_part} for group: {group_name}")
                        send_telegram_message(chat_id, f"Generating report for {group_name}, please wait...")
                        success, report_text = generate_report_text(group_name, sektor_list)
                        send_telegram_message(chat_id, report_text)
                        found_group = True; break
                if not found_group:
                    send_telegram_message(chat_id, "Sorry, that is not a valid report command.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return

            incident_ids = re.findall(r'\binc\d+\b', text, re.IGNORECASE)
            if incident_ids:
                print(f"Found incident IDs: {incident_ids}")
                unique_ids = sorted(list(set(id.upper() for id in incident_ids)))
                SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
                df_sqm = get_sheet_as_dataframe(SPREADSHEET_ID, "SQM")
                df_sqm['incident'] = df_sqm['incident'].str.upper()
                replies = []
                for incident_id in unique_ids:
                    result = df_sqm[df_sqm['incident'] == incident_id]
                    if not result.empty:
                        incident_data = result.iloc[0].to_dict()
                        summary_text = find_summary_in_insera(incident_id)
                        if summary_text: incident_data['summary'] = summary_text
                        replies.append(format_incident_details(incident_data))
                    else:
                        replies.append(f"❌ Tidak ditemukan di sheet SQM: <code>{incident_id}</code>")
                final_reply = "\n\n".join(replies)
                send_telegram_message(chat_id, final_reply, reply_to_message_id=message_id)

        except Exception as e:
            print(f"Error in handler: {e}")
            admin_chat_id = os.environ.get("MY_CHAT_ID", "").split(',')[0]
            if admin_chat_id: send_telegram_message(admin_chat_id, f"Bot Error in main handler: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        return
