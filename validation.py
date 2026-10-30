"""Protocol validation; no storage or HTTP side effects."""
import re
from uuid import UUID

class Invalid(ValueError): pass

def text(value, label, limit=256):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value): raise Invalid(label)
    return value

def uuid(value):
    try:
        if str(UUID(value)) != value: raise ValueError()
    except (ValueError,TypeError,AttributeError): raise Invalid("Invalid UUID")
    return value

def integer(value, low, high, label):
    if type(value) is not int or not low<=value<=high: raise Invalid(label)
    return value

def name(value): return text(value,"Invalid name",128)

def identity(value, world):
    if not isinstance(value,dict) or value.get("world")!=world: raise Invalid("Foreign world")
    if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",text(value.get("dimension"),"dimension")): raise Invalid("dimension")
    blocks=value.get("blocks")
    if not isinstance(blocks,list) or len(blocks) not in (1,2): raise Invalid("blocks")
    positions=[]
    for b in blocks:
        if not isinstance(b,dict): raise Invalid("block")
        positions.append(tuple(integer(b.get(k),-30000000 if k!='y' else -2048,30000000 if k!='y' else 2048,"coordinate") for k in ('x','y','z')))
    if len(positions)==2:
        a,b=positions
        if a[1]!=b[1] or abs(a[0]-b[0])+abs(a[2]-b[2])!=1: raise Invalid("double chest")
    return len(blocks)*27

def change(c, world):
    if not isinstance(c,dict): raise Invalid("change")
    uuid(c.get("changeId")); uuid(c.get("chestId"))
    integer(c.get("revision"),1,2**53-1,"revision")
    integer(c.get("baseServerRevision",0),0,2**53-1,"baseServerRevision")
    op=c.get("operation"); data=c.get("data")
    if op not in ('upsert','rename','delete','structure_changed') or not isinstance(data,dict): raise Invalid("operation/data")
    if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",text(c.get("dimension"),"dimension")): raise Invalid('dimension')
    if c.get('worldId',world)!=world: raise Invalid('worldId mismatch')
    if op in ('upsert','rename'): name(data.get('name'))
    if op=='upsert':
        if data.get('id',c['chestId'])!=c['chestId']: raise Invalid("chest id mismatch")
        slots=identity(data.get('identity'),world)
        if c['dimension']!=data['identity']['dimension']: raise Invalid('dimension mismatch')
        items=data.get('items')
        if not isinstance(items,list) or len(items)>slots: raise Invalid('items')
        seen=set()
        for item in items:
            if not isinstance(item,dict): raise Invalid('item')
            slot=integer(item.get('slot'),0,slots-1,'slot')
            if slot in seen: raise Invalid('duplicate slot')
            seen.add(slot)
            if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+",text(item.get('item_id'),'item id')): raise Invalid('item id')
            integer(item.get('count'),1,9999,'count')
        if type(data.get('structureChanged')) is not bool: raise Invalid('structureChanged')
        for key in ('createdAt','syncedAt'):
            if data.get(key) is not None:
                from datetime import datetime
                try: datetime.fromisoformat(data[key].replace('Z','+00:00'))
                except (ValueError,TypeError,AttributeError): raise Invalid('timestamp')
        if items and 'syncedAt' in data and data['syncedAt'] is None: raise Invalid('unconfirmed items')
    if op=='structure_changed' and type(data.get('structureChanged')) is not bool: raise Invalid('structureChanged')

def envelope(value):
    if not isinstance(value,dict) or type(value.get('protocolVersion')) is not int or value['protocolVersion']!=1: raise Invalid('Unsupported protocolVersion')
    uuid(value.get('clientId')); text(value.get('worldId'),'worldId')
    if not isinstance(value.get('changes'),list) or not 1<=len(value['changes'])<=256: raise Invalid('changes: expected 1..256')
    if type(value.get('bootstrap',False)) is not bool: raise Invalid('bootstrap')
    return value
