"""Public search endpoints observed in the services' own web clients.

Search metadata only; do not imply that a returned track is downloadable.
"""
import json
from urllib.parse import urlencode

def search(source, query, pages, fetch, quality):
    kind=source['adapter']
    rows={}
    limited=False
    for page in range(pages):
        if kind=='arcod':
            body,_=fetch('https://arcod.xyz/api/get-music?'+urlencode({'q':query,'offset':page*10}))
            payload=json.loads(body)
            if not payload.get('success'): raise ValueError('ARCOD не вернул успешный ответ')
            payload=payload['data']
            groups=[('track',payload.get('tracks',{})),('album',payload.get('albums',{}))]
        else:
            # This client endpoint exposes 25 results; no unverified pagination parameters.
            body,_=fetch('https://hifi.rhythmax.workers.dev/tracks?'+urlencode({'q':query}))
            groups=[('track',json.loads(body))]
        more=False
        for entity,group in groups:
            items=group.get('items',[])
            more |= group.get('total',group.get('totalNumberOfItems',len(items))) > (page+1)*len(items) if items else False
            for item in items:
                ident=str(item['id'])
                artist=(item.get('performer') or item.get('artist') or {}).get('name','')
                title=' — '.join(x for x in (artist,item.get('title','')) if x)
                bits=item.get('maximum_bit_depth') or 0
                rate=item.get('maximum_sampling_rate') or 0
                tags=item.get('mediaMetadata',{}).get('tags',[])
                lossless=item.get('audioQuality') in ('LOSSLESS','HI_RES_LOSSLESS') or any('LOSSLESS' in t for t in tags)
                evidence=(f'Каталог: {bits} bit / {rate} kHz' if bits and rate else 'Каталог: '+str(item.get('audioQuality','неизвестно')))
                q=quality(('Lossless ' if lossless or bits else '')+(f'{bits} bit {rate} kHz' if bits and rate else ''))
                # The service pages require pasting the identifier; retain it explicitly.
                original=item.get('url') or (f'https://tidal.com/track/{ident}' if kind=='tidal' else '')
                row={'title':title,'url':source['url'],'originalUrl':original,'source':source['name'],'sourceId':source['id'],
                     'quality':q,'evidence':evidence,'match':1,'entity':entity,'identifier':ident,
                     'note':'Трек' if entity=='track' else 'Альбом', 'copyText':original or title,
                     'metadataOnly':True, 'availability':item.get('downloadable')}
                row['note'] += ' · параметры каталога; скачивание через сервис не проверено. Откройте сервис и вставьте ссылку или название.'
                if item.get('downloadable') is False:row['note'] += ' Каталог помечает downloadable=false.'
                rows[entity+':'+ident]=row
        limited=more
        if not more or kind=='tidal':break
    return {'status':'ok' if rows else 'unconfirmed','results':list(rows.values()),'limited':limited,
            'message':f'Публичный API: {len(rows)} треков/альбомов; параметры из каталога, файлы не проверены'}
