"""Transactional SQLite repository. Server revisions are scoped to (world, chest)."""
import sqlite3,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
import validation as v

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':'))

SCHEMA = """
CREATE TABLE IF NOT EXISTS worlds(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chests(world_id TEXT NOT NULL REFERENCES worlds(id),id TEXT NOT NULL,name TEXT NOT NULL,dimension TEXT NOT NULL,identity_json TEXT NOT NULL,data_json TEXT NOT NULL,server_revision INTEGER NOT NULL CHECK(server_revision>0),deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(world_id,id));
CREATE TABLE IF NOT EXISTS chest_items(world_id TEXT NOT NULL,chest_id TEXT NOT NULL,slot INTEGER NOT NULL CHECK(slot>=0 AND slot<54),item_id TEXT NOT NULL,count INTEGER NOT NULL CHECK(count>0 AND count<=9999),PRIMARY KEY(world_id,chest_id,slot),FOREIGN KEY(world_id,chest_id) REFERENCES chests(world_id,id));
CREATE TABLE IF NOT EXISTS processed_changes(change_id TEXT PRIMARY KEY,client_id TEXT NOT NULL,world_id TEXT NOT NULL REFERENCES worlds(id),chest_id TEXT NOT NULL,revision INTEGER NOT NULL,request_hash TEXT NOT NULL,result TEXT NOT NULL,processed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS processed_client ON processed_changes(client_id,world_id,chest_id,revision);
CREATE TABLE IF NOT EXISTS server_changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,world_id TEXT NOT NULL REFERENCES worlds(id),chest_id TEXT NOT NULL,server_revision INTEGER NOT NULL,operation TEXT NOT NULL,data_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS changes_world_cursor ON server_changes(world_id,sequence);
CREATE INDEX IF NOT EXISTS chests_world_deleted ON chests(world_id,deleted);
PRAGMA user_version=1;
"""

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

class Repository:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db: db.executescript(SCHEMA)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15,factory=ClosingConnection); db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA journal_mode=WAL'); return db
    def sync(self,payload):
        v.envelope(payload); world=payload['worldId']; client=payload['clientId']; results=[]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            exists=db.execute('SELECT 1 FROM worlds WHERE id=?',(world,)).fetchone()
            if not exists and not payload.get('bootstrap'): raise v.Invalid('Unknown world: explicit bootstrap required')
            stamp=now(); db.execute('INSERT OR IGNORE INTO worlds VALUES(?,?,?)',(world,stamp,stamp))
            for c in payload['changes']:
                if isinstance(c,dict) and c.get('operation')=='upsert' and 'dimension' not in c:
                    data=c.get('data'); identity=data.get('identity') if isinstance(data,dict) else None
                    c=dict(c,dimension=identity.get('dimension') if isinstance(identity,dict) else None)
                try:
                    v.change(c,world)
                    if c.get('clientId',client)!=client: raise v.Invalid('clientId mismatch')
                except v.Invalid as e:
                    result={'changeId':c.get('changeId') if isinstance(c,dict) else None,'chestId':c.get('chestId') if isinstance(c,dict) else None,'revision':c.get('revision') if isinstance(c,dict) else None,'status':'rejected','reason':str(e)}
                    # Valid operation identities reserve their ID even if their data is rejected.
                    # Correcting data requires a NEW changeId, never reusing an old receipt.
                    try:
                        v.uuid(result['changeId']); v.uuid(result['chestId']); v.integer(result['revision'],1,2**53-1,'revision')
                    except v.Invalid: pass
                    else:
                        fingerprint=hashlib.sha256(encoded({'client':client,'world':world,'change':c}).encode()).hexdigest()
                        previous=db.execute('SELECT * FROM processed_changes WHERE change_id=?',(result['changeId'],)).fetchone()
                        if previous:
                            if previous['request_hash']!=fingerprint: result.update(reason='changeId reused with different content')
                            else: result=json.loads(previous['result'])
                        else: db.execute('INSERT INTO processed_changes VALUES(?,?,?,?,?,?,?,?)',(result['changeId'],client,world,result['chestId'],result['revision'],fingerprint,encoded(result),stamp))
                    results.append(result); continue
                fingerprint=hashlib.sha256(encoded({'client':client,'world':world,'change':c}).encode()).hexdigest()
                previous=db.execute('SELECT * FROM processed_changes WHERE change_id=?',(c['changeId'],)).fetchone()
                if previous:
                    if previous['request_hash']!=fingerprint:
                        result={k:c[k] for k in ('changeId','chestId','revision')}; result.update(status='rejected',reason='changeId reused with different content')
                    else:
                        result=json.loads(previous['result'])
                        if result['status']=='applied': result['status']='duplicate'
                    results.append(result); continue
                result=self.apply(db,world,client,c,stamp)
                db.execute('INSERT INTO processed_changes VALUES(?,?,?,?,?,?,?,?)',(c['changeId'],client,world,c['chestId'],c['revision'],fingerprint,encoded(result),stamp))
                results.append(result)
            db.execute('UPDATE worlds SET updated_at=? WHERE id=?',(stamp,world))
        return {'success':True,'protocolVersion':1,'results':results}
    def apply(self,db,world,client,c,stamp):
        row=db.execute('SELECT * FROM chests WHERE world_id=? AND id=?',(world,c['chestId'])).fetchone()
        revision=row['server_revision'] if row else 0
        result={k:c[k] for k in ('changeId','chestId','revision')}; result['serverRevision']=revision
        previous=db.execute("SELECT MAX(revision) FROM processed_changes WHERE client_id=? AND world_id=? AND chest_id=? AND json_extract(result,'$.status')='applied'",(client,world,c['chestId'])).fetchone()[0]
        if (previous is not None and c['revision']<=previous) or c.get('baseServerRevision',0)!=revision or row and row['deleted']:
            return dict(result,status='conflict',reason='Obsolete revision or tombstone')
        op=c['operation']
        if row and c['dimension']!=row['dimension']: return dict(result,status='rejected',reason='Dimension mismatch')
        if not row and op!='upsert': return dict(result,status='rejected',reason='Unknown chest')
        data=dict(c['data']) if op=='upsert' else json.loads(row['data_json'])
        data['id']=c['chestId']
        if not data.get('createdAt'): data['createdAt']=stamp
        if 'syncedAt' not in data: data['syncedAt']=stamp if data.get('items') else None
        if op=='rename': data['name']=c['data']['name']
        if op=='structure_changed': data['structureChanged']=c['data']['structureChanged']
        if row and op=='upsert' and encoded(data['identity'])!=row['identity_json']: return dict(result,status='rejected',reason='Identity immutable; use a new chest UUID')
        revision+=1
        values=(world,c['chestId'],data['name'],data['identity']['dimension'],encoded(data['identity']),encoded(data),revision,int(op=='delete'),stamp,stamp)
        db.execute('INSERT INTO chests VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,id) DO UPDATE SET name=excluded.name,data_json=excluded.data_json,server_revision=excluded.server_revision,deleted=excluded.deleted,updated_at=excluded.updated_at',values)
        if op=='upsert':
            db.execute('DELETE FROM chest_items WHERE world_id=? AND chest_id=?',(world,c['chestId']))
            db.executemany('INSERT INTO chest_items VALUES(?,?,?,?,?)',[(world,c['chestId'],i['slot'],i['item_id'],i['count']) for i in data['items']])
        event=dict(data,deleted=op=='delete',serverRevision=revision)
        db.execute('INSERT INTO server_changes(world_id,chest_id,server_revision,operation,data_json,created_at) VALUES(?,?,?,?,?,?)',(world,c['chestId'],revision,op,encoded(event),stamp))
        return dict(result,status='applied',serverRevision=revision)
    def worlds(self):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM worlds ORDER BY id')]
    def chests(self,world,chest=None):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM worlds WHERE id=?',(world,)).fetchone(): return None
            rows=db.execute('SELECT * FROM chests WHERE world_id=?'+(' AND id=?' if chest else '')+' ORDER BY id',(world,chest) if chest else (world,)).fetchall()
            return [dict(json.loads(r['data_json']),serverRevision=r['server_revision'],deleted=bool(r['deleted'])) for r in rows]
    def export(self,world):
        rows=self.chests(world)
        if rows is None: return None
        return {'formatVersion':1,'world':world,'chests':[{k:v for k,v in r.items() if k not in ('serverRevision','deleted')} for r in rows if not r['deleted']], 'tombstones':[r for r in rows if r['deleted']]}
    def changes(self,world,since,limit=100):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM worlds WHERE id=?',(world,)).fetchone(): return None
            rows=db.execute('SELECT * FROM server_changes WHERE world_id=? AND sequence>? ORDER BY sequence LIMIT ?',(world,since,limit+1)).fetchall()
            return {'changes':[dict(sequence=r['sequence'],chestId=r['chest_id'],operation=r['operation'],data=json.loads(r['data_json'])) for r in rows[:limit]],'nextCursor':rows[min(len(rows),limit)-1]['sequence'] if rows else since,'hasMore':len(rows)>limit}
