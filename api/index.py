import os
import json
import re
from http.server import BaseHTTPRequestHandler
import pandas as pd

from lib.report_generator import (
    generate_sqm_regional_report,
    generate_ccan_report,
    get_sheet_as_dataframe,
    send_telegram_message,
    SEKTOR_GROUPS
)

def format_incident_details(incident_data, ticket_type):
    """
    Formats incident details into a single, pipe-separated line
    by directly mapping a list of column keys to their values.
    """
    def get_clean_value(key):
        return str(incident_data.get(key, '')).strip().replace('\n', ' ')

    incident_id = get_clean_value('incident')
    header = f"📄 Respon {incident_id}:\n"
    
    if ticket_type == 'SQM(CCAN)':
        column_keys = [
            'incident', 'kategori loker', 'status', 'summary', 'customer name',
            'no hp', 'user', 'sto', 'segment', 'datek', 'interface',
            'ip', 'hasil ukur', 'sn'
        ]
    else: # Default to SQM
        column_keys = [
            'incident', 'kategori loker', 'status', 'summary', 'customer name',
            'no hp', 'user', 'sto', 'customer type', 'status sugar', 'datek',
            'interface', 'ip', 'hasil ukur', 
            'sn',
            'proses ttr 4 jam'
        ]

    report_parts = [get_clean_value(key) for key in column_keys]

    body = " | ".join(report_parts)
    return header + body


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
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
            authorized_user_ids = [uid for uid in all_authorized_ids if uid > 0]
            authorized_group_ids = [gid for gid in all_authorized_ids if gid < 0]
            if not ((chat_id in authorized_group_ids) or (chat_id > 0 and user_id in authorized_user_ids)):
                send_telegram_message(chat_id, "⛔️ Access denied.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            
            cleaned_command = text.lower().split('@')[0].strip().replace(" ", "")

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
                print(f"Found incident IDs: {incident_ids}")
                unique_ids = sorted(list(set(id.upper() for id in incident_ids)))
                SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
                df_all_tickets = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
                df_all_tickets['incident'] = df_all_tickets['incident'].str.upper()
                replies = []
                for incident_id in unique_ids:
                    result = df_all_tickets[df_all_tickets['incident'] == incident_id]
                    if not result.empty:
                        incident_data = result.iloc[0].to_dict()
                        ticket_type = incident_data.get('kategori loker', '').strip().upper()
                        formatted_reply = format_incident_details(incident_data, ticket_type)
                        replies.append(formatted_reply)
                    else:
                        replies.append(f"❌ Tidak ditemukan di sheet ALLTIKET: <code>{incident_id}</code>")
                
                final_reply = "\n\n".join(replies)
                send_telegram_message(chat_id, final_reply, reply_to_message_id=message_id)

        except Exception as e:
            print(f"ERROR in handler: {e}")
            admin_chat_id = os.environ.get("MY_CHAT_ID", "").split(',')[0]
            if admin_chat_id: send_telegram_message(admin_chat_id, f"Bot Error in main handler: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        return
