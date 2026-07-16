import http.server
import os

port = int(os.environ.get("PORT", 8000))

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

http.server.test(HandlerClass=NoCacheHandler, port=port)
