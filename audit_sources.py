"""Probe every candidate, then verify its discovered search with a homepage title."""
import concurrent.futures
import datetime
import json
from pathlib import Path
import server

CACHE=Path('audit-cache')
CACHE.mkdir(exist_ok=True)

def probe(source):
    result={**source}
    result['checkedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        if source.get('adapter') in ('arcod','tidal'):
            data=server.run_search(source,'Massive Attack',1)
            result['enabled']=data['status']=='ok'
            result['check']={'status':'verified' if result['enabled'] else 'unavailable','message':data['message'],'query':'Massive Attack'}
            return result
        html,base=server.fetch(source['url'])
        (CACHE/(source['id']+'.html')).write_text(html,encoding='utf-8')
        doc=server.Document(html).root
        if source['id']=='archive.org':
            rows,limited=server.archive_search('piano',1,source)
            result['enabled']=True
            result['check']={'status':'verified' if rows else 'empty','message':f'API поиска: {len(rows)} результатов','query':'piano'}
            return result
        headings=[n.text().strip() for n in doc.walk() if n.tag in ('h2','h3') and len(n.text().strip())>10]
        query=' '.join(server.tokens(headings[0])[:3]) if headings else 'music'
        if not query:query='music'
        url,data=server.search_form(doc,base,query)
        result['searchForm']={'url':url,'method':'POST' if data else 'GET'}
        html,current=server.fetch(url,data)
        (CACHE/(source['id']+'.search.html')).write_text(html,encoding='utf-8')
        if server.is_challenge(html):raise ValueError('CAPTCHA / проверка браузера')
        rows=server.candidates(server.Document(html).root,current,query,source)
        result['enabled']=True
        result['check']={'status':'verified' if rows else 'empty','message':f'Форма поиска отвечает; распознано {len(rows)} ссылок','query':query,'sample':rows[:2]}
    except Exception as e:
        result['enabled']=False
        result['check']={'status':'unavailable','message':str(e)[:220]}
    print(source['id']+' '+result['check']['status'],flush=True)
    return result

if __name__=='__main__':
    sources=json.loads(Path('sources.json').read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        checked=list(pool.map(probe,sources))
    checked.sort(key=lambda s:(not s['enabled'],not s['flac'],s['name'].casefold()))
    Path('sources.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPLETE',len(checked),sum(s['enabled'] for s in checked),flush=True)
