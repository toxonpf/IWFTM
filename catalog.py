"""FMHY inventory: preserve every entry and classify its integration scope."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

RAW_URL = 'https://raw.githubusercontent.com/fmhy/edit/main/docs/audio.md'
SECTIONS = {'Streaming Apps', 'Streaming Sites', 'Genre Specific Streaming', 'Specialty Streaming', 'Concerts / Live Shows',
            'Audio Ripping Sites', 'Download Sites', 'Genre Specific Ripping', 'Audio Torrenting',
            'Royalty Free Music', 'Media Soundtracks', 'Game Soundtracks'}
SUPPORT = {'github', 'discord', 'telegram', 'guide', 'support', 'updates', 'status', 'wiki', 'tools',
           'forum', 'interviews', 'backup', 'bulk downloader', 'use translator', 'search', 'mobile', 'web app'}

def inventory(markdown):
    section = ''
    records = []
    for lineno, line in enumerate(markdown.splitlines(), 1):
        if line.startswith('#'):
            section = re.sub(r'^[#\s►▷]+', '', line).strip()
        if not line.startswith('* '): continue
        head, _, description = line.partition(' - ')
        links = re.findall(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', head)
        if not links: continue
        for index, (name, url) in enumerate(links):
            name = name.replace('\u2060', '').strip()
            host = (urlsplit(url).hostname or '').removeprefix('www.')
            reason = ''
            if section not in SECTIONS:
                reason = 'Инструмент, радио, подкаст или справочный раздел; не каталог скачивания музыки'
            if section == 'Audio Ripping Tools':
                reason = 'Приложение/загрузчик: нужен установленный клиент и его настройка; веб-форма сайта не ищет музыку'
            if section == 'Telegram Bots':
                reason = 'Нужны Telegram и взаимодействие с ботом; общий веб-поиск неприменим'
            if name.lower() in SUPPORT and index > 0 and not (name.lower()=='web app' and section=='Streaming Apps'):
                reason = 'Вспомогательная ссылка на документацию или сообщество'
            if host in ('github.com','gitlab.com','discord.gg','discord.com','t.me','reddit.com','redd.it','rentry.co','rentry.org','cse.google.com','wikipedia.org'):
                reason = 'Программа, бот, сообщество или индекс; требуется отдельный клиент/вход, не прямой веб-поиск'
            if re.search(r'Radio(?:\s|$)|MIDI Files|Tracker|Database|Tracking|Index(?:es)?(?:\s|$)', description, re.I) and section != 'Download Sites':
                reason = 'Радио, база метаданных или индекс, а не каталог скачивания релизов'
            record = dict(name=name if not name.isdigit() else links[0][0]+' · '+host, url=url,
                          id=host+'-'+hashlib.sha1(url.encode()).hexdigest()[:7], section=section,
                          flac=bool(re.search(r'FLAC|Lossless|ALAC|Hi-Res',description,re.I)),
                          disposition='excluded' if reason else 'candidate', reason=reason, line=lineno)
            if host == 'bandcamp.com': record['flac']=True
            if host == 'archive.org': record['flac']=True
            records.append(record)
    return records

def source_list(records):
    found={}
    for r in records:
        if r['disposition'] != 'candidate': continue
        host=(urlsplit(r['url']).hostname or '').removeprefix('www.')
        if host in found:
            found[host]['flac'] |= r['flac']
            if r['section'] not in found[host]['sections']: found[host]['sections'].append(r['section'])
            continue
        found[host]={**r, 'id':host, 'sections':[r['section']], 'adapter':'html', 'enabled':False,
                     'check':{'status':'pending','message':'Ещё не проверен'}}
    if 'archive.org' in found: found['archive.org']['adapter']='archive'
    if 'arcod.xyz' in found: found['arcod.xyz']['adapter']='arcod'
    if 'tidal-dl.pages.dev' in found: found['tidal-dl.pages.dev']['adapter']='tidal'
    return list(found.values())

if __name__ == '__main__':
    records=inventory(Path('fmhy-audio.md').read_text(encoding='utf-8'))
    Path('inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    sources=source_list(records)
    Path('sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(records)} entries; {len(sources)} website candidates; {sum(s["flac"] for s in sources)} lossless candidates')
