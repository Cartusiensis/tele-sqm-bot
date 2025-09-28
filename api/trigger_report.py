import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin
from lib.report_generator import SEKTOR_GROUPS

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Get the full list of region names to process
            regions_to_process = list(SEKTOR_GROUPS.keys())
            
            if not regions_to_process:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"No regions configured to report.")
                return

            # Construct the URL for the worker function
            base_url = f"https://{os.environ.get('VERCEL_URL')}"
            worker_url = urljoin(base_url, "/api/hourly_report")

            # Prepare the data payload for the first call in the chain
            payload = {"regions_left": regions_to_process}
            
            print(f"CHAIN_STARTER: Kicking off report chain at {worker_url} for regions: {regions_to_process}")

            # Make a single, blocking request to start the first job.
            # This call is very fast, as it only triggers the next function.
            requests.post(worker_url, json=payload, timeout=10)

            # Instantly respond to the cron job service
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"Accepted: Report chain has been successfully initiated.")
            print("CHAIN_STARTER: Successfully triggered the first worker.")

        except Exception as e:
            print(f"CHAIN_STARTER: CRITICAL ERROR - Could not start the report chain: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Error: Could not initiate the report chain.")
        
        return