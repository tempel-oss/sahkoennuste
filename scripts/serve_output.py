
from pathlib import Path
import http.server, socketserver, socket
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"output"
PORT=8765
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(OUT),**kwargs)

def local_ip():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8",80))
        return s.getsockname()[0]
    except Exception:
        return "TAMAN-KONEEN-IP"
    finally:
        s.close()

print("Paikallinen ennustesivu kaynnissa.")
print(f"Tietokoneella: http://127.0.0.1:{PORT}/")
print(f"Puhelimessa samassa Wi-Fi-verkossa: http://{local_ip()}:{PORT}/")
print("Pida tama ikkuna auki. Lopeta Ctrl+C.")
with socketserver.ThreadingTCPServer(("0.0.0.0",PORT),Handler) as httpd:
    httpd.serve_forever()
