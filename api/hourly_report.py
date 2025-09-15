import os
from http.server import BaseHTTPRequestHandler
from lib.report_generator import generate_report_text, send_telegram_message

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Get the string of chat IDs from the environment variable
        report_recipients_str = os.environ.get("MY_CHAT_ID")
        
        if not report_recipients_str:
            print("MY_CHAT_ID environment variable is not set. Cannot send report.")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Report recipient list not configured.")
            return

        # --- Split the string into a list of individual IDs ---
        recipient_ids = report_recipients_str.split(',')

        # Generate the report text just once
        success, report_text = generate_report_text()
        
        # --- Loop through each ID and send the message ---
        for chat_id in recipient_ids:
            if chat_id: # Ensure don't process empty strings
                try:
                    print(f"Sending report to chat_id: {chat_id.strip()}")
                    send_telegram_message(chat_id.strip(), report_text)
                except Exception as e:
                    # Log if sending to one recipient fails, but continue to the next
                    print(f"Failed to send report to {chat_id.strip()}: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Report generation triggered for all recipients.")
        return