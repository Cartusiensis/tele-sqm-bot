import os
from http.server import BaseHTTPRequestHandler
from lib.report_generator import (
    generate_sqm_regional_report, 
    generate_ccan_report, 
    send_telegram_message,
    SEKTOR_GROUPS
)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        report_recipients_str = os.environ.get("MY_CHAT_ID")
        if not report_recipients_str:
            print("MY_CHAT_ID environment variable is not set.")
            self.send_response(500); self.end_headers(); self.wfile.write(b"Config error."); return

        recipient_ids = report_recipients_str.split(',')

        # --- Part 1: Generate and Send Regional SQM Reports ---
        for group_name, sektor_list in SEKTOR_GROUPS.items():
            print(f"Generating SQM regional report for group: {group_name}")
            success, report_text = generate_sqm_regional_report(group_name, sektor_list)
            
            # Send this specific report (or error) to all recipients
            for chat_id in recipient_ids:
                if chat_id:
                    try:
                        send_telegram_message(chat_id.strip(), report_text)
                    except Exception as e:
                        print(f"Failed to send SQM report for {group_name} to {chat_id.strip()}: {e}")
        
        # --- Part 2: Generate and Send the Global SQM(CCAN) Report ---
        print("Generating SQM(CCAN) report...")
        success, ccan_report_text = generate_ccan_report()

        # Send this single global report (or error) to all recipients
        for chat_id in recipient_ids:
            if chat_id:
                try:
                    send_telegram_message(chat_id.strip(), ccan_report_text)
                except Exception as e:
                    print(f"Failed to send global SQM(CCAN) report to {chat_id.strip()}: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"All hourly reports triggered.")
        return