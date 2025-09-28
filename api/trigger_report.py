# api/trigger_report.py

import os
import requests
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin

def run_report_in_background():
    """
    This function runs on a separate thread. It makes a request to the 
    real hourly_report endpoint and waits for it to finish, but it does
    not block the main response to the cron job service.
    """
    try:
        # Vercel provides the full URL of the current deployment automatically.
        # This is the key to making it work in both preview and production.
        base_url = f"https://{os.environ.get('VERCEL_URL')}"
        report_url = urljoin(base_url, "/api/hourly_report")
        
        print(f"TRIGGER: Kicking off long-running report at: {report_url}")
        
        # We use POST because it's better for triggering actions.
        # The timeout is for the background task itself, not the cron job.
        response = requests.post(report_url, timeout=240) # 4 minute timeout
        
        print(f"TRIGGER: Background report task finished. Status: {response.status_code}, Body: {response.text}")

    except Exception as e:
        print(f"TRIGGER: Error in background report thread: {e}")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Create a new thread that will run our background function.
        thread = threading.Thread(target=run_report_in_background)
        
        # 2. Start the thread. The code in run_report_in_background will start executing.
        thread.start()
        
        # 3. IMMEDIATELY send a success response back to cron-job.org.
        #    We don't wait for the thread to finish.
        self.send_response(202) # "Accepted" is the perfect status code for this.
        self.end_headers()
        self.wfile.write(b"Accepted: Hourly report job has been triggered in the background.")
        print("TRIGGER: Sent 202 Accepted response to cron service. Task is now running in background.")
        return