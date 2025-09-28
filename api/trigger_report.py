import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin
from lib.report_generator import SEKTOR_GROUPS

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            regions_to_process = list(SEKTOR_GROUPS.keys())
            
            if not regions_to_process:
                self.send_response(200); self.end_headers(); self.wfile.write(b"No regions to report."); return

            base_url = f"https://{os.environ.get('VERCEL_URL')}"
            worker_url = urljoin(base_url, "/api/hourly_report")

            payload = {"regions_left": regions_to_process}
            
            print(f"TRIGGER: Firing request to start report chain for regions: {regions_to_process}")

            # We will send the request but use a tiny timeout. We EXPECT this to time out
            # during a cold start, but the request will have already been sent to Vercel's network.
            # We will catch the expected timeout and treat it as a success.
            try:
                requests.post(worker_url, json=payload, timeout=1) # Use a 1-second timeout
            except requests.exceptions.ReadTimeout:
                # This is the EXPECTED outcome during a cold start. It's a success.
                print("TRIGGER: Request sent. Timed out as expected (fire and forget). The chain is running.")
                pass # Continue normally
            
            # Instantly respond to the cron job service
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"Accepted: Report chain has been successfully initiated.")

        except Exception as e:
            # This will now only catch critical errors, like VERCEL_URL not being set.
            print(f"TRIGGER: CRITICAL ERROR - Could not initiate request: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Error: Could not initiate the report chain.")
        
        return