"""Explicit, loopback-only static routes. Never map request paths to arbitrary files."""
from pathlib import Path
import ipaddress

WEB_ROOT=Path(__file__).resolve().parent/'web'
ASSETS={'/':('index.html','text/html; charset=utf-8'),'/index.html':('index.html','text/html; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/chest.svg':('chest.svg','image/svg+xml'),'/placeholder.svg':('placeholder.svg','image/svg+xml')}
CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://blocksitems.com; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"

def serve_web(handler,path):
    asset=ASSETS.get(path)
    if asset is None: return False
    if not ipaddress.ip_address(handler.client_address[0]).is_loopback or not ipaddress.ip_address(handler.server.server_address[0]).is_loopback:
        handler.reply(403,{'error':'Web interface is available on loopback only'}); return True
    filename,mime=asset; target=WEB_ROOT/filename
    if not target.is_file() or target.is_symlink(): handler.reply(404,{'error':'Asset not found'}); return True
    body=target.read_bytes(); handler.send_response(200)
    for key,value in [('Content-Type',mime),('Content-Length',str(len(body))),('Cache-Control','no-cache'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',CSP)]: handler.send_header(key,value)
    handler.end_headers()
    try: handler.wfile.write(body)
    except (BrokenPipeError,ConnectionResetError): pass
    return True
