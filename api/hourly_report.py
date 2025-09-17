import os
from http.server import BaseHTTPRequestHandler
from lib.report_generator import generate_report_text, send_telegram_message
from lib.report_generator import SEKTOR_GROUPS

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        report_recipients_str = os.environ.get("MY_CHAT_ID")
        if not report_recipients_str:
            print("MY_CHAT_ID environment variable is not set.")
            self.send_response(500); self.end_headers(); self.wfile.write(b"Config error."); return

        recipient_ids = report_recipients_str.split(',')

        for group_name, sektor_list in SEKTOR_GROUPS.items():
            print(f"Generating report for group: {group_name}")
            success, report_text = generate_report_text(group_name, sektor_list)
            if success:
                for chat_id in recipient_ids:
                    if chat_id:
                        try:
                            send_telegram_message(chat_id.strip(), report_text)
                        except Exception as e:
                            print(f"Failed to send report for {group_name} to {chat_id.strip()}: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"All sector reports triggered.")
        return