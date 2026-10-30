import argparse,json
from pathlib import Path
from repository import Repository
p=argparse.ArgumentParser(); p.add_argument('--database',type=Path,default=Path(__file__).parent/'data'/'chestcount.db'); p.add_argument('--world'); p.add_argument('--chest'); a=p.parse_args()
if not a.database.exists(): p.error('Database does not exist; start the server first')
r=Repository(a.database)
print(json.dumps(r.chests(a.world,a.chest) if a.world else r.worlds(),ensure_ascii=False,indent=2))
