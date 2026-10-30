"""Local Chest Count API. Standard library only; not for public deployment."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,unquote,parse_qs
import argparse,json,logging,os,uuid
from logging.handlers import RotatingFileHandler
from repository import Repository
from validation import Invalid,envelope
from web_routes import serve_web

MAX_BYTES=8*1024*1024
class LocalDevelopmentPolicy:
    """Future authentication seam. No fictitious accounts or credentials."""
    def authorize(self,handler,payload): return True

def make_server(host,port,db_path,legacy_dir=None,policy=None):
    repository=Repository(db_path); legacy_dir=Path(legacy_dir or Path(db_path).parent); policy=policy or LocalDevelopmentPolicy()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(15)
        def log_message(self,fmt,*args): logging.info('%s %s %s',self.address_string(),getattr(self,'command','?'),urlsplit(getattr(self,'path','/')).path)
        def reply(self,status,data):
            body=json.dumps(data,ensure_ascii=False).encode('utf-8')
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError): pass
        def do_POST(self):
            try:
                if self.headers.get('Transfer-Encoding'): return self.reply(400,{'error':'Content-Length required'})
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>MAX_BYTES: return self.reply(413,{'error':'Request size limit'})
                raw=self.rfile.read(length)
                if len(raw)!=length: raise Invalid('Incomplete body')
                payload=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(Invalid('Non-finite number')))
                if self.path=='/api/sync':
                    if not isinstance(payload,dict) or not isinstance(payload.get('chests'),list): raise Invalid('Expected legacy snapshot')
                    legacy_dir.mkdir(parents=True,exist_ok=True)
                    target=legacy_dir/('legacy_'+str(uuid.uuid4())+'.json')
                    with target.open('x',encoding='utf-8') as file: json.dump(payload,file,ensure_ascii=False,indent=2)
                    return self.reply(200,{'success':True,'received':len(payload['chests']),'legacy':True})
                if self.path!='/api/v1/sync': return self.reply(404,{'error':'Not found'})
                envelope(payload)
                if not policy.authorize(self,payload): return self.reply(403,{'error':'Forbidden'})
                self.reply(200,repository.sync(payload))
            except (Invalid,ValueError,UnicodeDecodeError) as e: self.reply(400,{'error':str(e) if isinstance(e,Invalid) else 'Invalid JSON or headers'})
            except (TimeoutError,OSError): logging.exception('Request I/O failure'); self.reply(408,{'error':'Request interrupted'})
            except Exception: logging.exception('Sync failure'); self.reply(500,{'error':'Internal server error'})
        def do_GET(self):
            try:
                url=urlsplit(self.path)
                if serve_web(self,url.path): return
                parts=[unquote(p) for p in url.path.split('/') if p]
                if any(p in ('.','..') or '/' in p or '\\' in p for p in parts): return self.reply(400,{'error':'Invalid identifier'})
                if parts==['api','v1','health']: return self.reply(200,{'success':True,'protocolVersion':1,'service':'chestcount'})
                if parts==['api','v1','worlds']: return self.reply(200,{'worlds':repository.worlds()})
                result=None
                if len(parts)>=5 and parts[:3]==['api','v1','worlds']:
                    world=parts[3]
                    if parts[4]=='chests' and len(parts) in (5,6):
                        rows=repository.chests(world,parts[5] if len(parts)==6 else None)
                        result=({'chests':rows} if len(parts)==5 else rows[0] if rows else None) if rows is not None else None
                    elif parts[4]=='export' and len(parts)==5: result=repository.export(world)
                    elif parts[4]=='changes' and len(parts)==5:
                        query=parse_qs(url.query); since=int(query.get('since',['0'])[0]); limit=int(query.get('limit',['100'])[0])
                        if since<0 or not 1<=limit<=256: raise ValueError()
                        result=repository.changes(world,since,limit)
                self.reply(404,{'error':'Not found'}) if result is None else self.reply(200,result)
            except (ValueError,Invalid): self.reply(400,{'error':'Invalid request'})
            except Exception: logging.exception('Query failure'); self.reply(500,{'error':'Internal server error'})
    server=ThreadingHTTPServer((host,port),Handler); server.daemon_threads=True; server.repository=repository
    return server

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default=os.getenv('CHESTCOUNT_HOST','127.0.0.1')); parser.add_argument('--port',type=int,default=int(os.getenv('CHESTCOUNT_PORT','8080'))); parser.add_argument('--database',type=Path,default=root/'data'/'chestcount.db'); args=parser.parse_args()
    logs=root/'logs'; logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.StreamHandler(),RotatingFileHandler(logs/'server.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')])
    server=make_server(args.host,args.port,args.database,root/'data'); logging.info('Chest Count listening on %s:%d (local test API)',args.host,args.port)
    try: server.serve_forever()
    except KeyboardInterrupt: logging.info('Stopping Chest Count')
    finally: server.server_close()
if __name__=='__main__': main()
