import unittest,tempfile,threading,json,uuid,urllib.request,urllib.error,sqlite3,concurrent.futures
from pathlib import Path
from server import make_server,MAX_BYTES
from repository import Repository

def uid(): return str(uuid.uuid4())
def chest(world,chest_id=None,count=32):
    return {'id':chest_id or uid(),'name':'Minerios','identity':{'world':world,'dimension':'minecraft:overworld','blocks':[{'x':100,'y':64,'z':200}]},'items':[{'slot':0,'item_id':'minecraft:diamond','count':count}],'createdAt':'2026-10-30T00:00:00Z','syncedAt':'2026-10-30T00:00:00Z','structureChanged':False}
def change(data,revision=1,base=0,op='upsert'):
    return {'changeId':uid(),'chestId':data['id'],'revision':revision,'baseServerRevision':base,'dimension':'minecraft:overworld','operation':op,'data':data}

class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.db=self.root/'test.db'; self.repo=Repository(self.db); self.world='local:test:'+uid(); self.client=uid(); self.data=chest(self.world)
        self.server=make_server('127.0.0.1',0,self.db,self.root/'legacy'); self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def payload(self,changes,client=None,bootstrap=True): return {'protocolVersion':1,'clientId':client or self.client,'worldId':self.world,'bootstrap':bootstrap,'changes':changes}
    def call(self,path,payload=None,raw=None):
        data=raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        req=urllib.request.Request(self.base+path,data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=10) as r: return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e: return e.code,json.load(e)
    def sync(self,c,client=None): return self.call('/api/v1/sync',self.payload([c],client))[1]['results'][0]
    def initial(self):
        c=change(self.data); self.assertEqual('applied',self.sync(c)['status']); return c
    def test_create_world_chest_and_items(self):
        self.initial(); self.assertEqual(1,len(self.repo.worlds())); stored=self.repo.chests(self.world)[0]; self.assertEqual(32,stored['items'][0]['count']); self.assertEqual(1,stored['serverRevision'])
    def test_update_same_chest(self):
        self.initial(); self.data['items'][0]['count']=48; self.assertEqual('applied',self.sync(change(self.data,2,1))['status']); self.assertEqual(1,len(self.repo.chests(self.world))); self.assertEqual(48,self.repo.chests(self.world)[0]['items'][0]['count'])
    def test_rename_only_preserves_inventory(self):
        self.initial(); self.assertEqual('applied',self.sync(change({'id':self.data['id'],'name':'New'},2,1,'rename'))['status']); row=self.repo.chests(self.world)[0]; self.assertEqual('New',row['name']); self.assertEqual(32,row['items'][0]['count'])
    def test_structure_preserves_inventory(self):
        self.initial(); self.sync(change({'id':self.data['id'],'structureChanged':True},2,1,'structure_changed')); row=self.repo.chests(self.world)[0]; self.assertTrue(row['structureChanged']); self.assertEqual(32,row['items'][0]['count'])
    def test_tombstone_prevents_resurrection(self):
        self.initial(); self.assertEqual('applied',self.sync(change({'id':self.data['id']},2,1,'delete'))['status']); self.assertTrue(self.repo.chests(self.world)[0]['deleted']); self.assertEqual('conflict',self.sync(change(self.data,3,2))['status'])
    def test_duplicate_change_id(self):
        c=self.initial(); result=self.sync(c); self.assertEqual('duplicate',result['status']); self.assertEqual(1,result['serverRevision']); self.assertEqual(1,len(self.repo.changes(self.world,0)['changes']))
    def test_changed_payload_same_id_rejected(self):
        c=self.initial(); c['data']['name']='Altered'; self.assertEqual('rejected',self.sync(c)['status'])
    def test_rejected_id_cannot_be_reused_with_corrected_data(self):
        data=chest(self.world); data['name']=''; c=change(data)
        self.assertEqual('rejected',self.sync(c)['status']); data['name']='Corrected'
        self.assertEqual('rejected',self.sync(c)['status']); self.assertEqual([],self.repo.chests(self.world))
    def test_local_revision_is_not_global(self):
        self.initial(); self.assertEqual('conflict',self.sync(change(self.data,99999,0),uid())['status']); self.assertEqual('applied',self.sync(change(self.data,1,1),uid())['status'])
    def test_same_client_obsolete_revision(self):
        self.initial(); self.assertEqual('conflict',self.sync(change(self.data,1,1))['status'])
    def test_conflict_is_durable_and_not_duplicate_success(self):
        self.initial(); c=change(self.data,2,0); self.assertEqual('conflict',self.sync(c)['status']); self.assertEqual('conflict',self.sync(c)['status'])
    def test_invalid_json_and_protocol(self):
        self.assertEqual(400,self.call('/api/v1/sync',raw=b'{bad')[0]); p=self.payload([change(self.data)]); p['protocolVersion']=2; self.assertEqual(400,self.call('/api/v1/sync',p)[0])
    def test_too_large(self):
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request('POST','/api/v1/sync',body=b'',headers={'Content-Length':str(MAX_BYTES+1)})
            response=connection.getresponse(); self.assertEqual(413,response.status); response.read()
        finally: connection.close()
    def test_unknown_world_requires_bootstrap(self): self.assertEqual(400,self.call('/api/v1/sync',self.payload([change(self.data)],bootstrap=False))[0]); self.assertEqual(404,self.call('/api/v1/worlds/unknown/chests')[0])
    def test_export_and_query_routes(self):
        self.initial(); self.assertEqual(200,self.call('/api/v1/health')[0]); self.assertEqual(1,len(self.call('/api/v1/worlds')[1]['worlds'])); self.assertEqual(200,self.call('/api/v1/worlds/'+self.world+'/chests/'+self.data['id'])[0]); export=self.call('/api/v1/worlds/'+self.world+'/export')[1]; self.assertEqual(1,export['formatVersion']); self.assertEqual(self.data,export['chests'][0])
    def test_global_cursor_pagination(self):
        self.initial(); second=chest(self.world); second['identity']['blocks'][0]['x']=101; self.sync(change(second)); self.sync(change({'id':self.data['id'],'name':'New'},2,1,'rename'))
        page=self.call('/api/v1/worlds/'+self.world+'/changes?since=0&limit=1')[1]; self.assertTrue(page['hasMore']); next_page=self.repo.changes(self.world,page['nextCursor']); self.assertEqual(2,len(next_page['changes'])); self.assertGreater(next_page['nextCursor'],page['nextCursor'])
    def test_restart_persists_sqlite_and_idempotency(self):
        c=self.initial(); repo=Repository(self.db); self.assertEqual(1,len(repo.chests(self.world))); self.assertEqual('duplicate',repo.sync(self.payload([c]))['results'][0]['status'])
    def test_transaction_rolls_back_inventory_and_receipt(self):
        self.initial()
        with self.repo.connect() as db: db.execute("CREATE TRIGGER fail_items BEFORE INSERT ON chest_items WHEN NEW.count=48 BEGIN SELECT RAISE(ABORT,'injected'); END")
        self.data['items'][0]['count']=48; self.assertEqual(500,self.call('/api/v1/sync',self.payload([change(self.data,2,1)]))[0]); self.assertEqual(32,self.repo.chests(self.world)[0]['items'][0]['count']); self.assertEqual(1,self.repo.chests(self.world)[0]['serverRevision']); self.assertEqual(1,len(self.repo.changes(self.world,0)['changes']))
    def test_concurrent_same_change(self):
        c=change(self.data)
        with concurrent.futures.ThreadPoolExecutor(4) as pool: results=list(pool.map(lambda _:self.sync(c)['status'],range(4)))
        self.assertEqual(1,results.count('applied')); self.assertEqual(3,results.count('duplicate'))
    def test_validation_types_slots_coordinates_names(self):
        for edit in [lambda d:d.update(name=''),lambda d:d['items'][0].update(slot=27),lambda d:d['items'][0].update(count=True),lambda d:d['identity']['blocks'][0].update(x=30000001),lambda d:d['identity'].update(world='foreign')]:
            d=chest(self.world); edit(d); self.assertEqual('rejected',self.sync(change(d))['status'])
    def test_world_scoped_chest_id(self):
        self.initial(); other='local:other'; d=chest(other,self.data['id']); payload=self.payload([change(d)]); payload['worldId']=other; self.assertEqual('applied',self.call('/api/v1/sync',payload)[1]['results'][0]['status']); self.assertEqual(2,len(self.repo.worlds()))
    def test_legacy_does_not_touch_database(self):
        code,result=self.call('/api/sync',{'world':'legacy','chests':[self.data]}); self.assertEqual(200,code); self.assertTrue(result['legacy']); self.assertEqual([],self.repo.worlds()); self.assertEqual(1,len(list((self.root/'legacy').glob('*.json'))))
    def test_path_traversal_and_invalid_cursor(self):
        self.assertEqual(400,self.call('/api/v1/worlds/%2E%2E/chests')[0]); self.assertEqual(400,self.call('/api/v1/worlds/test/changes?since=-1')[0])
if __name__=='__main__': unittest.main(verbosity=2)
