"""make_catalog.py - merge catalog.seed.json with cartridges/*.json sidecars into catalog.json.

The seed lists every course a teacher might type in, with its kits marked pending
and (where known) the live Canvas course id a future pull should read. A sidecar
with the same kit id flips that kit to ready and supplies the download details.
"""
import datetime
import glob
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def main():
    with open(os.path.join(ROOT, 'catalog.seed.json'), encoding='utf-8') as fh:
        seed = json.load(fh)
    sidecars = {}
    for p in glob.glob(os.path.join(ROOT, 'cartridges', '*.json')):
        with open(p, encoding='utf-8') as fh:
            s = json.load(fh)
        sidecars[s['id']] = s
    used = set()
    for course in seed['courses']:
        for kit in course.get('kits', []):
            s = sidecars.get(kit['id'])
            if s:
                used.add(kit['id'])
                kit.update({k: s[k] for k in ('label', 'file', 'bytes', 'version', 'built', 'front_page', 'items',
                                                'modules', 'counts', 'weights', 'weighted', 'source', 'status')})
                kit['warnings'] = s['verify']['warnings']
                if not course.get('canvas_title'):
                    course['canvas_title'] = s['title']
            else:
                kit.setdefault('status', 'pending')
    orphans = sorted(set(sidecars) - used)
    if orphans:
        raise SystemExit('sidecars with no seed entry: %s (add them to catalog.seed.json)' % orphans)
    seed['generated'] = datetime.datetime.now().isoformat(timespec='seconds')
    with open(os.path.join(ROOT, 'catalog.json'), 'w', encoding='utf-8') as fh:
        json.dump(seed, fh, indent=1, ensure_ascii=False)
    ready = [(c['code'], k['id']) for c in seed['courses'] for k in c['kits'] if k.get('status') == 'ready']
    print('catalog.json: %d courses, %d kits ready: %s' % (len(seed['courses']), len(ready), ready))


if __name__ == '__main__':
    main()
