import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin
from lib.report_generator import (
    generate_sqm_regional_report, 
    generate_ccan_report, 
    send_telegram_message,
    SEKTOR_GROUPS
)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1. Get the list of jobs from the incoming request
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        payload = json.loads(post_data)
        regions_left = payload.get("regions_left", [])

        if not regions_left:
            print("CHAIN_LINK: Received empty region list. Nothing to do.")
            self.send_response(200); self.end_headers(); self.wfile.write(b"No regions to process."); return

        # 2. Process ONLY the first item in the list
        current_region = regions_left.pop(0) # Take the first region and remove it from the list
        print(f"CHAIN_LINK: ---> Processing report for region: {current_region}")
        
        # --- Actual Work for this one region ---
        recipient_ids = os.environ.get("MY_CHAT_ID", "").split(',')
        sektor_list = SEKTOR_GROUPS.get(current_region)
        if sektor_list:
            success, report_text = generate_sqm_regional_report(current_region, sektor_list)
            for chat_id in recipient_ids:
                if chat_id: send_telegram_message(chat_id.strip(), report_text)
        # --- End of Work ---

        # 3. Check if there are more jobs left in the chain
        if regions_left:
            # If yes, trigger the next job with the remaining list of regions.
            # THIS IS NOW A SYNCHRONOUS, BLOCKING CALL. NO THREADING.
            try:
                base_url = f"https://{os.environ.get('VERCEL_URL')}"
                worker_url = urljoin(base_url, "/api/hourly_report")
                new_payload = {"regions_left": regions_left}
                
                print(f"CHAIN_LINK: Triggering next job for regions: {regions_left}")
                # This call will wait until the next function is triggered, guaranteeing execution.
                requests.post(worker_url, json=new_payload, timeout=10)
                print(f"CHAIN_LINK: Successfully triggered next job.")

            except Exception as e:
                print(f"CHAIN_LINK: CRITICAL ERROR - Could not trigger next job. Chain broken. Error: {e}")
        else:
            # This was the last regional report. Now, send the final global CCAN report.
            print("CHAIN_LINK: All regional reports done. Sending final global CCAN report.")
            success, ccan_report_text = generate_ccan_report()
            for chat_id in recipient_ids:
                if chat_id: send_telegram_message(chat_id.strip(), ccan_report_text)
            print("CHAIN_COMPLETE: All jobs finished.")

        # 4. Send a success response for the job we just completed.
        print(f"CHAIN_LINK: <--- Finished processing {current_region}. Responding OK.")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"OK: Processed {current_region}.".encode())
        return
