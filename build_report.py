"""Create a reviewable report from the saved live audit."""
import json
from pathlib import Path
from collections import Counter

def build():
    sources=json.loads(Path('sources.json').read_text(encoding='utf-8'))
    records=json.loads(Path('inventory.json').read_text(encoding='utf-8'))
    counts=Counter(s['check']['status'] for s in sources)
    usable=[s for s in sources if s['enabled']]
    lines=['# Проверка источников FMHY','', 'Дата: 6 сентября 2026 года. [Каталог](https://fmhy.net/audio), [официальный исходник](https://github.com/fmhy/edit/blob/main/docs/audio.md).','',
           f'Реестр: {len(records)} основных и вспомогательных ссылок; для сетевой проверки выделено {len(sources)} уникальных доменов. В inventory.json сохранены причины исключения остальных записей.', '',
           f'Автопоиск включён для {len(usable)} сайтов, из них {sum(s["flac"] for s in usable)} с заявленным lossless. Распознанные результаты: {counts["verified"]} источников; ответ без распознанных совпадений: {counts["empty"]}; недоступны/неподдерживаемый интерфейс: {counts["unavailable"]}.', '',
           'Ответ без совпадений не доказывает исправность поиска. Метаданные не подтверждают доступность скачивания и качество файла. Проверка сети относится к текущему подключению; программы и боты требуют отдельного клиента.', '',
           '| Источник | Раздел | Lossless заявлен | Проверка | Результат |','|---|---|---|---|---|']
    for s in sorted(sources,key=lambda x:(not x['enabled'],not x['flac'],x['name'].casefold())):
        msg=s['check']['message'].replace('|','/').replace('\n',' ')
        lines.append(f'| [{s["name"]}]({s["url"]}) | {s["section"]} | {"Да" if s["flac"] else "Не указан"} | {s["check"]["status"]} | {msg} |')
    Path('SOURCES-AUDIT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(len(sources),dict(counts),len(usable),sum(s['flac'] for s in usable))

if __name__=='__main__':build()
