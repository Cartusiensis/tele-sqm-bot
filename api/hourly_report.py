import os
from http.server import BaseHTTPRequestHandler
from lib.report_generator import (
    generate_sqm_regional_report, 
    generate_ccan_report, 
    send_telegram_message,
    SEKTOR_GROUPS
)

class handler(BaseHTTPRequestHandler):
    def _run_reports(self):
        """
        This new helper method contains all the original, long-running logic.
        """
        print("WORKER: Starting the report generation process...")
        report_recipients_str = os.environ.get("MY_CHAT_ID")
        if not report_recipients_str:
            print("WORKER: MY_CHAT_ID environment variable is not set.")
            return

        recipient_ids = report_recipients_str.split(',')

        # Part 1: Regional SQM Reports
        for group_name, sektor_list in SEKTOR_GROUPS.items():
            print(f"WORKER: Generating SQM regional report for group: {group_name}")
            success, report_text = generate_sqm_regional_report(group_name, sektor_list)
            for chat_id in recipient_ids:
                if chat_id: send_telegram_message(chat_id.strip(), report_text)
        
        # Part 2: Global SQM(CCAN) Report
        print("WORKER: Generating global SQM(CCAN) report...")
        success, ccan_report_text = generate_ccan_report()
        for chat_id in recipient_ids:
            if chat_id: send_telegram_message(chat_id.strip(), ccan_report_text)
        
        print("WORKER: All reports have been generated and sent.")

    def do_GET(self):
        """Handles manual runs from a browser, like you do for testing."""
        self._run_reports()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Success: All hourly reports triggered via GET and completed.")
        return

    def do_POST(self):
        """
        This new method handles the background call from our trigger function.
        """
        self._run_reports()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Success: All hourly reports triggered via POST and completed.")
        return
