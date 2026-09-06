"""Local music metasearch. Python 3.11+, no dependencies."""
import concurrent.futures
import ipaddress
import json
import re
import socket
import threading
import unicodedata
import urllib.parse as U
import urllib.request as R
import adapters
import catalog
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG_URL = 'https://fmhy.net/audio'
UA = 'IWFTM/1.0 (local music search)'
LIMIT = 3_000_000
GATE = threading.BoundedSemaphore(8)

def public_url(url):
    p = U.urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('Недопустимый адрес источника')
    for info in socket.getaddrinfo(p.hostname, p.port or 443):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError('Локальные адреса источников запрещены')
    return url

class Redirect(R.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch(url, data=None):
    public_url(url)
    req = R.Request(url, data=data, headers={'User-Agent': UA, 'Accept': 'text/html,application/json'})
    with R.build_opener(Redirect).open(req, timeout=12) as response:
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Страница превышает лимит 3 МБ')
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'), response.url

class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []
    def text(self):
        if self.tag in ('script', 'style', 'nav', 'footer', 'aside'):
            return ''
        return ' '.join(x.text() if isinstance(x, Node) else x for x in self.children)
    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for x in self.children:
            if isinstance(x, Node):
                yield from x.walk(tag)

class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.current)
        self.current.children.append(n)
        if tag not in ('input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'col'):
            self.current = n
    def handle_endtag(self, tag):
        n = self.current
        while n.parent:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent
    def handle_data(self, data):
        self.current.children.append(data)

def parse_catalog(html):
    section = False
    found = {}
    for n in Document(html).root.walk():
        if n.tag in ('h2', 'h3'):
            if section:
                break
            section = 'download sites' in n.text().lower()
        if section and n.tag == 'a':
            url = n.attrs.get('href', '')
            p = U.urlsplit(url)
            if p.scheme not in ('http', 'https') or not p.hostname:
                continue
            host = p.hostname.removeprefix('www.')
            if host in ('fmhy.net', 'rentry.co', 'cse.google.com'):
                continue
            name = ' '.join(n.text().split()).strip('\u2060')
            if name and not name.isdigit():
                found[host] = {'id': host, 'name': name, 'url': url}
    if len(found) < 5:
        raise ValueError('Не удалось распознать раздел Download Sites')
    return list(found.values())

CATALOG = json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))

def tokens(text):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold())

def quality(text):
    formats = [f for f in ('FLAC', 'ALAC', 'WAV', 'AIFF', 'APE', 'MP3', 'AAC', 'OGG', 'OPUS', 'M4A') if re.search(r'\b' + f + r'\b', text, re.I)]
    lossless = any(f in formats for f in ('FLAC', 'ALAC', 'WAV', 'AIFF', 'APE')) or bool(re.search(r'\blossless\b', text, re.I))
    bits = re.findall(r'\b(16|24|32)\s*[- ]?bit\b', text, re.I)
    rates = re.findall(r'\b(44[.,]1|48|88[.,]2|96|176[.,]4|192|352[.,]8|384)\s*kHz\b', text, re.I)
    bitrate = re.findall(r'\b(64|96|128|160|192|224|256|320)\s*(?:kbps|kb/s|kbit)', text, re.I)
    bit = max(map(int, bits), default=0)
    rate = max((float(x.replace(',', '.')) for x in rates), default=0)
    kbps = max(map(int, bitrate), default=0)
    label = ' / '.join(formats) or ('Lossless' if lossless else 'Качество неизвестно')
    if bit: label += f' · {bit} bit'
    if rate: label += f' · {rate:g} kHz'
    if kbps: label += f' · {kbps} kbps'
    return {'label': label, 'lossless': lossless, 'bits': bit, 'rate': rate, 'kbps': kbps,
            'rank': [2 if lossless else 1 if formats or kbps else 0, bit if lossless else 0, rate if lossless else 0, kbps if not lossless else 0]}

def same_site(a, b):
    return (U.urlsplit(a).hostname or '').removeprefix('www.') == (U.urlsplit(b).hostname or '').removeprefix('www.')

def is_challenge(html):
    return bool(re.search(r'cf-chl-|<title>\s*Just a moment|verify you are human|captcha-container', html, re.I))

def search_form(doc, base, query):
    for form in doc.walk('form'):
        inputs = list(form.walk('input'))
        if any(n.attrs.get('type')=='password' for n in inputs):continue
        if form.attrs.get('action','').startswith('#'):continue
        field = next((n for n in inputs if n.attrs.get('name') in ('s', 'q', 'query', 'search', 'story', 'searchword', 'search_query', 'keys', 't', 'result', 'keyword', 'keywords', 'SearchTorrentsForm[nameTorrent]') and n.attrs.get('type', 'text') in ('text', 'search') and 'disabled' not in n.attrs), None)
        if field is None:
            continue
        url = U.urljoin(base, form.attrs.get('action') or base)
        if not same_site(url, base):
            continue
        values = {n.attrs['name']: n.attrs.get('value', '') for n in inputs if n.attrs.get('type') == 'hidden' and 'name' in n.attrs}
        values[field.attrs['name']] = query
        encoded = U.urlencode(values)
        if form.attrs.get('method', 'get').lower() == 'post':
            return url, encoded.encode()
        return url + ('&' if '?' in url else '?') + encoded, None
    raise ValueError('Автопоиск недоступен: не найдена форма поиска; откройте сайт вручную')

def candidates(doc, base, query, source):
    results = {}
    wanted = set(tokens(query))
    for a in doc.walk('a'):
        ancestor=a.parent
        ignored=False
        while ancestor:
            if ancestor.tag in ('nav','aside','header','footer'):ignored=True;break
            ancestor=ancestor.parent
        if ignored:continue
        title = ' '.join(a.text().split())
        href = U.urljoin(base, a.attrs.get('href', ''))
        p = U.urlsplit(href)
        if href.rstrip('/')==base.rstrip('/'):continue
        if p.scheme not in ('https', 'http') or not same_site(base, href) or (not p.path.strip('/') and not p.query) or p.fragment:
            continue
        if re.search(r'/(tag|category|search|page|author|login|register)(/|\b)', p.path):
            continue
        matched = wanted & set(tokens(title))
        if not wanted or len(matched) / len(wanted) < 0.6 or len(title) < 4:
            continue
        ancestor = a
        while ancestor.parent and ancestor.tag not in ('h1', 'h2', 'h3', 'h4', 'article', 'li'):
            ancestor = ancestor.parent
        # Only the result title is quality evidence: surrounding pages can mix releases.
        q = quality(title)
        results[href] = {'title': title, 'url': href, 'source': source['name'], 'sourceId': source['id'],
                         'quality': q, 'evidence': title, 'match': round(len(matched) / len(wanted), 2),
                         'note': 'Совпадение по названию; качество заявлено в заголовке, файл не проверен'}
    return list(results.values())

def archive_search(query, pages, source):
    quoted = ' AND '.join('"' + t + '"' for t in tokens(query))
    args = U.urlencode({'q': f'mediatype:audio AND ({quoted})', 'output': 'json', 'rows': pages * 50, 'page': 1})
    body, _ = fetch('https://archive.org/advancedsearch.php?' + args)
    response = json.loads(body)['response']
    rows = []
    for d in response['docs']:
        title = str(d.get('title', d['identifier']))
        rows.append({'title': title, 'url': 'https://archive.org/details/' + U.quote(d['identifier'], safe=''), 'source': source['name'], 'sourceId': source['id'], 'quality': quality(title), 'evidence': title, 'match': 1, 'note': 'Аудиозапись Internet Archive; параметры файла не проверены'})
    return rows, response['numFound'] > len(rows)

def run_search(source, query, pages):
    rows = {}
    try:
        with GATE:
            if source.get('adapter') in ('arcod','tidal'):
                return adapters.search(source,query,pages,fetch,quality)
            if source['id'] == 'archive.org':
                items, limited = archive_search(query, pages, source)
                return {'status': 'ok', 'results': items, 'limited': limited, 'message': 'Поиск по метаданным Internet Archive'}
            html, base = fetch(source['url'])
            url, data = search_form(Document(html).root, base, query)
            visited = set()
            limited = False
            for page in range(pages):
                if url in visited: break
                visited.add(url)
                html, current = fetch(url, data)
                if is_challenge(html):
                    raise ValueError('Сайт требует CAPTCHA или проверку браузера')
                doc = Document(html).root
                for result in candidates(doc, current, query, source):
                    rows[result['url']] = result
                next_link = next((a for a in doc.walk('a') if 'next' in a.attrs.get('rel', '').split() or a.text().strip().lower() in ('next', 'next page', 'следующая', 'далее', '»')), None)
                if next_link is None: break
                nxt = U.urljoin(current, next_link.attrs.get('href', ''))
                if not same_site(nxt, base) or nxt in visited: break
                limited = page == pages - 1
                url, data = nxt, None
            # Bound additional requests; keep every candidate even if its detail cannot be read.
            def enrich(row):
                try:
                    info = detail(row['url'])
                    if info['evidence']:
                        row.update(info)
                except Exception:
                    row['note'] += '; описание недоступно'
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(enrich, list(rows.values())[:12]))
        return {'status': 'ok' if rows else 'unconfirmed', 'results': list(rows.values()), 'limited': limited,
                'message': (f'Просмотрено страниц: {len(visited)}. Автопроверка качества: до 12 описаний.' if rows else 'Совпадений не распознано. Это не доказывает отсутствие музыки на сайте.')}
    except Exception as e:
        return {'status': 'error', 'message': str(e)[:250], 'results': list(rows.values()), 'limited': True}

def detail(url):
    html, _ = fetch(url)
    doc = Document(html).root
    if U.urlsplit(url).hostname=='downloads.khinsider.com':
        table=next((n for n in doc.walk('table') if n.attrs.get('id')=='songlist'),None)
        headers=next(table.walk('tr'),None) if table else None
        evidence=' '.join(headers.text().split()) if headers else ''
        return {'quality':quality(evidence),'evidence':evidence,'note':'Форматы из заголовка таблицы треков Khinsider; файлы не проверены'}
    content = next((n for n in doc.walk() if any(c in n.attrs.get('class', '').split() for c in ('entry-content','post-content','post_content','full-story','fullstory','post-body','post-single-content')) or n.attrs.get('itemprop') == 'articleBody'), None)
    if content is None:
        return {'quality': quality(''), 'evidence': '', 'note': 'Не удалось выделить описание релиза; проверьте страницу вручную'}
    text = ' '.join(content.text().split())[:15000]
    # Restrict evidence to explicit format/quality metadata to avoid track listings and recommendations.
    snippets = re.findall(r'(?:Format|Quality|Bitrate|Формат|Качество)\s*:.{0,100}?(?=\b\w+\s*:|$)', text, re.I)
    evidence = ' | '.join(snippets)[:600]
    return {'quality': quality(evidence), 'evidence': evidence, 'note': 'Параметры из описания релиза; возможны несколько форматов. Файл не проверен.'}

class Handler(BaseHTTPRequestHandler):
    def reply(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        if self.path == '/api/sources':
            return self.reply({'sources': CATALOG, 'origin': CATALOG_URL})
        if self.path == '/api/inventory':
            return self.reply(json.loads((ROOT/'inventory.json').read_text(encoding='utf-8')))
        names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        name = names.get(self.path)
        if not name: return self.reply({'error': 'Не найдено'}, 404)
        raw = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[name.split('.')[-1]] + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        global CATALOG
        if self.headers.get('Host') not in ('127.0.0.1:8765', 'localhost:8765') or self.headers.get('Origin') not in (None, 'http://127.0.0.1:8765', 'http://localhost:8765'):
            return self.reply({'error': 'Недопустимый источник запроса'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 8192: raise ValueError('Слишком большой запрос')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/refresh':
                markdown, _ = fetch(catalog.RAW_URL)
                records=catalog.inventory(markdown)
                updated=catalog.source_list(records)
                if len(updated)<20:raise ValueError('Каталог не распознан; сохранён предыдущий список')
                old={s['id']:s for s in CATALOG}
                for source in updated:
                    previous=old.get(source['id'],{})
                    if previous.get('url')==source['url']:
                        for key in ('adapter','enabled','check','checkedAt'):
                            if key in previous:source[key]=previous[key]
                updated.sort(key=lambda s:(not s['enabled'],not s['flac'],s['name'].casefold()))
                tmp=ROOT/'sources.tmp'
                tmp.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
                tmp.replace(ROOT/'sources.json')
                (ROOT/'inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
                CATALOG=updated
                return self.reply({'sources': CATALOG})
            source = next((s for s in CATALOG if s['id'] == data.get('source')), None)
            if not source: raise ValueError('Неизвестный источник')
            if self.path == '/api/search':
                q = str(data.get('query', '')).strip()
                if not tokens(q) or len(q) > 200: raise ValueError('Введите запрос длиной до 200 символов')
                return self.reply(run_search(source, q, min(5, max(1, int(data.get('pages', 2))))))
            if self.path == '/api/detail':
                url = str(data.get('url', ''))
                if not same_site(source['url'], url): raise ValueError('Адрес не принадлежит источнику')
                with GATE: result = detail(url)
                return self.reply(result)
            self.reply({'error': 'Не найдено'}, 404)
        except Exception as e:
            self.reply({'error': str(e)[:250]}, 400)

if __name__ == '__main__':
    print('IWFTM: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
