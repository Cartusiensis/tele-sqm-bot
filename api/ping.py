from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # This function's only job is to respond as fast as possible.
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        self.wfile.write(b"pong")
        print("PING: Keep-alive ping received, container is warm.")
        return