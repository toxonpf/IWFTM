"""Optional real-network smoke test: python smoke_live.py."""
import json
import server
for host in ('intmusic.net','musicrider.org','archive.org'):
    source=next(s for s in server.CATALOG if s['id']==host)
    result=server.run_search(source,'Massive Attack',1)
    print(json.dumps({'source':host, 'status':result['status'],'message':result['message'],'count':len(result['results']),'sample':result['results'][:1]},ensure_ascii=True),flush=True)
