import os
import json
import re
from http.server import BaseHTTPRequestHandler
import pandas as pd

# Import reusable functions
from lib.report_generator import generate_report_text, get_sheet_as_dataframe, send_telegram_message

def format_incident_details(incident_data):
    # ... (this function does not need to change)
    def esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    lines = [f"📄 Detail Ticket: <code>{esc(incident_data.get('incident', 'N/A'))}</code>"]
    field_map = {
        '• Contact Name': 'contact name', '• No HP': 'no hp', '• User': 'user',
        '• Customer Type': 'customer type', '• DATEK': 'datek', '• STO': 'sto',
        '• Status Sugar': 'status sugar', '• Proses TTR 4 Jam': 'proses ttr 4 jam', '• SN': 'sn'
    }
    for label, col_name in field_map.items():
        if col_name in incident_data and pd.notna(incident_data[col_name]) and incident_data[col_name] != '':
            lines.append(f"{label}: {esc(incident_data[col_name])}")
    return "\n".join(lines)


# --- VERCEL'S MAIN HANDLER ---
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # --- SETUP & PARSING ---
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            update = json.loads(post_data)

            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            text = message.get("text", "").strip()
            
            # --- NEW: Get the ID of the message to reply to ---
            message_id = message.get("message_id")

            if not all([chat_id, user_id, text, message_id]):
                self.send_response(200); self.end_headers(); return

            # --- LOAD AUTHORIZATION LISTS ---
            all_authorized_ids_str = os.environ.get("MY_CHAT_ID", "")
            all_authorized_ids = [int(i) for i in all_authorized_ids_str.split(',') if i]
            
            authorized_user_ids = [uid for uid in all_authorized_ids if uid > 0]
            authorized_group_ids = [gid for gid in all_authorized_ids if gid < 0]

            # --- AUTHORIZATION LOGIC ---
            is_authorized_user = user_id in authorized_user_ids
            is_in_authorized_group = chat_id in authorized_group_ids
            is_private_chat = chat_id > 0

            has_permission = False
            if is_in_authorized_group:
                has_permission = True
            elif is_private_chat and is_authorized_user:
                has_permission = True

            if not has_permission:
                print(f"Unauthorized access by user {user_id} in chat {chat_id}.")
                # Reply to the unauthorized message
                send_telegram_message(chat_id, "⛔️ You are not authorized to use this bot in this chat.", reply_to_message_id=message_id)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
            
            # --- PERMISSION GRANTED - PROCESS THE COMMAND ---
            
            # Handle the /laporantiket command
            if text.startswith("/laporantiket"):
                send_telegram_message(chat_id, "Generating report, please wait...", reply_to_message_id=message_id)
                success, report_text = generate_report_text()
                # The final report is a new message, not a reply, which is cleaner.
                send_telegram_message(chat_id, report_text)
            
            # Handle incident lookups
            else:
                incident_ids = re.findall(r'\binc\d+\b', text, re.IGNORECASE)
                if incident_ids:
                    unique_ids = sorted(list(set(id.upper() for id in incident_ids)))
                    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
                    df = get_sheet_as_dataframe(SPREADSHEET_ID, "SQM")
                    df['incident'] = df['incident'].str.upper()
                    
                    replies = []
                    for incident_id in unique_ids:
                        result = df[df['incident'] == incident_id]
                        if not result.empty:
                            incident_data = result.iloc[0].to_dict()
                            replies.append(format_incident_details(incident_data))
                        else:
                            replies.append(f"❌ Tidak ditemukan: <code>{incident_id}</code>")
                    
                    final_reply = "\n\n".join(replies)
                    # --- MODIFIED: Pass the message_id to create a reply ---
                    send_telegram_message(chat_id, final_reply, reply_to_message_id=message_id)

        except Exception as e:
            # General error handling
            print(f"Error in handler: {e}")
            admin_chat_id = os.environ.get("MY_CHAT_ID", "").split(',')[0]
            if admin_chat_id:
                send_telegram_message(admin_chat_id, f"Bot Error in main handler: {e}")
        
        # Always acknowledge the request to Telegram
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        return
