import os
import json
import re
from http.server import BaseHTTPRequestHandler
import pandas as pd

# Imports from lib/report_generator are correct and unchanged
from lib.report_generator import (
    generate_sqm_regional_report,
    generate_ccan_report,
    get_sheet_as_dataframe,
    send_telegram_message,
    find_summary_in_insera,
    SEKTOR_GROUPS
)

def format_incident_details(incident_data, ticket_type):
    """
    Formats incident details differently based on the ticket type ('SQM' or 'SQM(CCAN)').
    """
    def esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    field_map_sqm = {
        '• Contact Name': 'contact name', '• No HP': 'no hp', '• User': 'user',
        '• Customer Type': 'customer type', '• DATEK': 'datek', '• STO': 'sto',
        '• Status Sugar': 'status sugar', '• Hasil Ukur': 'hasil ukur',
        '• Proses TTR 4 Jam': 'proses ttr 4 jam', '• SN': 'sn',
        '• Summary': 'summary'
    }

    field_map_ccan = {
        '• Contact Name': 'contact name', '• No HP': 'no hp', '• User': 'user',
        '• Customer Segment': 'customer segment',
        '• DATEK': 'datek', '• STO': 'sto',
        '• Hasil Ukur': 'hasil ukur',
        '• SN': 'sn',
        '• Summary': 'summary'
    }

    # Determine which template to use
    if ticket_type == 'SQM(CCAN)':
        field_map = field_map_ccan
        title_type = "SQM(CCAN)"
    else:
        # Default to SQM for safety, covering 'SQM' and any other unknown types
        field_map = field_map_sqm
        title_type = "SQM"

    lines = [f"📄 Detail Ticket {title_type}: <code>{esc(incident_data.get('incident', 'N/A'))}</code>"]
    
    # Loop through the chosen template and build the response
    for label, col_name in field_map.items():
        value = incident_data.get(col_name)
        if pd.notna(value) and str(value) != '':
            lines.append(f"{label}: {esc(value)}")
            
    return "\n".join(lines)


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


            # --- MODIFIED: Intelligent Incident Lookup Logic ---
            incident_ids = re.findall(r'\binc\d+\b', text, re.IGNORECASE)
            if incident_ids:
                print(f"Found incident IDs: {incident_ids}")
                unique_ids = sorted(list(set(id.upper() for id in incident_ids)))
                
                SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
                
                # Step 1: Fetch data ONCE from both sheets for efficiency
                df_all_tickets = get_sheet_as_dataframe(SPREADSHEET_ID, "ALLTIKET")
                df_all_tickets['incident'] = df_all_tickets['incident'].str.upper()

                df_insera = get_sheet_as_dataframe(SPREADSHEET_ID, "INSERA")
                df_insera['incident'] = df_insera['incident'].str.upper()
                # Keep only the columns we need for enrichment
                df_insera_enrichment = df_insera[['incident', 'summary', 'customer segment']]

                replies = []
                for incident_id in unique_ids:
                    result_all = df_all_tickets[df_all_tickets['incident'] == incident_id]
                    
                    if not result_all.empty:
                        # Convert the main ticket data to a dictionary
                        incident_data = result_all.iloc[0].to_dict()
                        
                        # Step 2: Enrich with data from INSERA sheet
                        result_insera = df_insera_enrichment[df_insera_enrichment['incident'] == incident_id]
                        if not result_insera.empty:
                            insera_data = result_insera.iloc[0].to_dict()
                            # Add the enrichment data to our main dictionary
                            incident_data.update(insera_data)

                        # Step 3: Determine ticket type and call the intelligent formatter
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