"""HTTP/static and SQLite fixture tests. No writes to the real data directory."""
import unittest,tempfile,threading,json,urllib.request,urllib.error,uuid
from pathlib import Path
from server import make_server
from repository import Repository,now

class WebFixture:
    def __init__(self,host='127.0.0.1'):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.db=self.root/'test.db'; self.repository=Repository(self.db)
        self.world='local:web test|default'; self.empty_world='local:empty'; self.client=str(uuid.uuid4()); self.revision=0
        self.single=self.record('A · Minérios',1,[{'slot':0,'item_id':'minecraft:diamond','count':32},{'slot':13,'item_id':'minecraft:iron_ingot','count':64},{'slot':26,'item_id':'minecraft:oak_log','count':16}])
        self.double=self.record('B · Equipamento',2,[{'slot':27,'item_id':'minecraft:oak_log','count':64},{'slot':53,'item_id':'minecraft:netherite_sword','count':1}])
        self.empty=self.record('C · Vazio',1,[]); self.deleted=self.record('D · Antigo',1,[])
        self.apply(self.single);self.apply(self.double);self.apply(self.empty);self.apply(self.deleted)
        self.apply(self.deleted,'delete',1)
        with self.repository.connect() as db: db.execute('INSERT INTO worlds VALUES(?,?,?)',(self.empty_world,'2025-01-01T00:00:00Z','2025-01-01T00:00:00Z'))
        self.server=make_server(host,0,self.db,self.root/'legacy')
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.05),daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def record(self,name,blocks,items):
        return {'id':str(uuid.uuid4()),'name':name,'identity':{'world':self.world,'dimension':'minecraft:overworld','blocks':[{'x':100+i,'y':64,'z':200} for i in range(blocks)]},'items':items,'createdAt':'2026-10-30T10:00:00Z','syncedAt':'2026-10-30T11:00:00Z','structureChanged':False}
    def apply(self,record,operation='upsert',base=0):
        self.revision+=1
        change={'changeId':str(uuid.uuid4()),'chestId':record['id'],'revision':self.revision,'baseServerRevision':base,'dimension':'minecraft:overworld','operation':operation,'data':record if operation=='upsert' else {}}
        return self.repository.sync({'protocolVersion':1,'clientId':self.client,'worldId':self.world,'bootstrap':True,'changes':[change]})
    def close(self): self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

class WebHttpTest(unittest.TestCase):
    def setUp(self): self.fixture=WebFixture()
    def tearDown(self): self.fixture.close()
    def get(self,path):
        try:
            with urllib.request.urlopen(self.fixture.base+path,timeout=5) as response:return response.status,dict(response.headers),response.read()
        except urllib.error.HTTPError as error:
            with error:return error.code,dict(error.headers),error.read()
    def test_html_css_javascript_and_local_placeholders(self):
        for path,mime in [('/','text/html'),('/index.html','text/html'),('/style.css','text/css'),('/app.js','text/javascript'),('/placeholder.svg','image/svg+xml'),('/chest.svg','image/svg+xml')]:
            status,headers,body=self.get(path);self.assertEqual(200,status,path);self.assertTrue(headers['Content-Type'].startswith(mime));self.assertTrue(body)
        self.assertIn('pixelated',self.get('/style.css')[2].decode());self.assertIn('lang="pt-PT"',self.get('/')[2].decode())
    def test_security_headers_and_filesystem_isolation(self):
        status,headers,body=self.get('/');self.assertEqual('nosniff',headers['X-Content-Type-Options']);self.assertIn("script-src 'self'",headers['Content-Security-Policy']);self.assertIn('https://blocksitems.com',headers['Content-Security-Policy'])
        for path in ['/server.py','/repository.py','/data/chestcount.db','/running-server.json','/web/app.js','/%2e%2e/server.py','/app.js/../server.py','/%2fetc/passwd']:
            self.assertIn(self.get(path)[0],(400,404),path)
    def test_real_sqlite_worlds_chests_and_detail(self):
        from urllib.parse import quote
        base='/api/v1/worlds/'+quote(self.fixture.world,safe='')
        self.assertEqual(2,len(json.loads(self.get('/api/v1/worlds')[2])['worlds']))
        self.assertEqual(4,len(json.loads(self.get(base+'/chests')[2])['chests']))
        single=json.loads(self.get(base+'/chests/'+self.fixture.single['id'])[2]);self.assertEqual(13,single['items'][1]['slot']);self.assertEqual(64,single['items'][1]['count']);self.assertEqual(1,single['serverRevision'])
        double=json.loads(self.get(base+'/chests/'+self.fixture.double['id'])[2]);self.assertEqual(2,len(double['identity']['blocks']));self.assertEqual(53,double['items'][1]['slot'])
        deleted=json.loads(self.get(base+'/chests/'+self.fixture.deleted['id'])[2]);self.assertTrue(deleted['deleted'])
    def test_empty_world_and_health_remain_supported(self):
        self.assertEqual([],json.loads(self.get('/api/v1/worlds/local%3Aempty/chests')[2])['chests']);self.assertTrue(json.loads(self.get('/api/v1/health')[2])['success'])
    def test_static_reads_do_not_change_database(self):
        with self.fixture.repository.connect() as db: before='\n'.join(db.iterdump())
        for path in ['/','/style.css','/app.js','/placeholder.svg','/api/v1/health','/api/v1/worlds']:self.get(path)
        with self.fixture.repository.connect() as db:self.assertEqual(before,'\n'.join(db.iterdump()))
    def test_database_without_any_worlds_serves_empty_response(self):
        server=make_server('127.0.0.1',0,self.fixture.root/'empty.db');thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.05),daemon=True);thread.start()
        try:
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/v1/worlds',timeout=5) as response:self.assertEqual({'worlds':[]},json.load(response))
        finally:server.shutdown();server.server_close();thread.join()
    def test_static_not_exposed_on_non_loopback_binding(self):
        fixture=WebFixture('0.0.0.0')
        try:
            with self.assertRaises(urllib.error.HTTPError) as context:urllib.request.urlopen(fixture.base+'/',timeout=5)
            self.assertEqual(403,context.exception.code);context.exception.close()
            with urllib.request.urlopen(fixture.base+'/api/v1/health',timeout=5) as response:self.assertEqual(200,response.status)
        finally:fixture.close()

if __name__=='__main__':unittest.main(verbosity=2)
