# api/index.py - Version with a Canary Log

import os
import json
import re
from http.server import BaseHTTPRequestHandler
import pandas as pd

from lib.report_generator import (
    generate_sqm_regional_report, generate_ccan_report,
    get_sheet_as_dataframe, send_telegram_message,
    find_summary_in_insera, SEKTOR_GROUPS
)

# ... (format_incident_details function is unchanged) ...
def format_incident_details(incident_data):
    def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    lines = [f"📄 Detail Ticket: <code>{esc(incident_data.get('incident', 'N/A'))}</code>"]
    field_map = {'• Contact Name': 'contact name', '• No HP': 'no hp', '• User': 'user', '• Customer Type': 'customer type', '• DATEK': 'datek', '• STO': 'sto', '• Status Sugar': 'status sugar', '• Hasil Ukur': 'hasil ukur', '• Proses TTR 4 Jam': 'proses ttr 4 jam', '• SN': 'sn', '• Summary': 'summary'}
    for label, col_name in field_map.items():
        if col_name in incident_data and pd.notna(incident_data[col_name]) and incident_data[col_name] != '':
            lines.append(f"{label}: {esc(incident_data[col_name])}")
    return "\n".join(lines)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # --- !! CANARY LOG !! ---
        # If you don't see this in the Vercel logs, the new code is NOT running.
        print("--- CANARY LOG: index.py v1.0 POST handler started ---")
        try:
            # ... (the rest of the code is the same as the last version) ...
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            update = json.loads(post_data)
            message = update.get("message") or update.get("edited_message")
            if not message:
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            chat_id, user_id, text, message_id = message.get("chat", {}).get("id"), message.get("from", {}).get("id"), message.get("text", "").strip(), message.get("message_id")
            if not all([chat_id, user_id, text, message_id]):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            all_authorized_ids = [int(i) for i in os.environ.get("MY_CHAT_ID", "").split(',') if i]
            if not any(id in [chat_id, user_id] for id in all_authorized_ids if id > 0) and chat_id not in [id for id in all_authorized_ids if id < 0]:
                send_telegram_message(chat_id, "⛔️ Access denied.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            
            cleaned_command = text.lower().split('@')[0].strip().replace(" ", "")
            print(f"DEBUG: Received text: '{text}', Cleaned command: '{cleaned_command}'")

            if cleaned_command.startswith('/sqm'):
                if cleaned_command == '/sqmccan':
                    print("MATCHED COMMAND: /sqmccan")
                    send_telegram_message(chat_id, "Generating global SQM(CCAN) report...")
                    success, report_text = generate_ccan_report()
                    send_telegram_message(chat_id, report_text)
                else:
                    found_group = False
                    for group_name, sektor_list in SEKTOR_GROUPS.items():
                        if cleaned_command == f"/sqm{group_name.lower()}":
                            print(f"MATCHED COMMAND: {cleaned_command} for group: {group_name}")
                            send_telegram_message(chat_id, f"Generating report for {group_name}...")
                            success, report_text = generate_sqm_regional_report(group_name, sektor_list)
                            send_telegram_message(chat_id, report_text)
                            found_group = True
                            break
                    if not found_group:
                        send_telegram_message(chat_id, "Sorry, that is not a valid report command.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            
            incident_ids = re.findall(r'\binc\d+\b', text, re.IGNORECASE)
            if incident_ids:
                df_all_tickets = get_sheet_as_dataframe(os.environ.get("SPREADSHEET_ID"), "ALLTIKET")
                df_all_tickets['incident'] = df_all_tickets['incident'].str.upper()
                replies = []
                for incident_id in sorted(list(set(id.upper() for id in incident_ids))):
                    result = df_all_tickets[df_all_tickets['incident'] == incident_id]
                    if not result.empty:
                        incident_data = result.iloc[0].to_dict()
                        summary_text = find_summary_in_insera(incident_id)
                        if summary_text: incident_data['summary'] = summary_text
                        replies.append(format_incident_details(incident_data))
                    else:
                        replies.append(f"❌ Tidak ditemukan di sheet ALLTIKET: <code>{incident_id}</code>")
                send_telegram_message(chat_id, "\n\n".join(replies), reply_to_message_id=message_id)

        except Exception as e:
            print(f"ERROR in handler: {e}")
            admin_chat_id = os.environ.get("MY_CHAT_ID", "").split(',')[0]
            if admin_chat_id: send_telegram_message(admin_chat_id, f"Bot Error in main handler: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        return
