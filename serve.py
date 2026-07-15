import http.server
import os

port = int(os.environ.get("PORT", 8000))
http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, port=port)
