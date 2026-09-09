"""build_kit.py - spec.json -> cartridges/<kit>.imscc + cartridges/<kit>.json sidecar.

The sidecar is what the Course Kit widget reads (through catalog.json): where the
front page lives inside the zip, the module identifiers a home page can link to,
counts, weights, and the verify result. A kit that fails verification is deleted
so it can never be published half-built.

usage: build_kit.py <spec.json> <kit-id> --label "Semester 1" [--version YYYY.MM.DD]
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import cc  # noqa: E402


def main():
    argv = sys.argv[1:]
    label, version = 'Semester 1', datetime.date.today().strftime('%Y.%m.%d')
    if '--label' in argv:
        i = argv.index('--label'); label = argv[i + 1]; del argv[i:i + 2]
    if '--version' in argv:
        i = argv.index('--version'); version = argv[i + 1]; del argv[i:i + 2]
    if len(argv) != 2:
        print(__doc__); sys.exit(2)
    spec_path, kit = argv
    with open(spec_path, encoding='utf-8') as fh:
        spec = json.load(fh)
    spec['course']['version'] = version
    spec['course']['date'] = datetime.date.today().isoformat()
    out = os.path.join(ROOT, 'cartridges', kit + '.imscc')
    rep = cc.build(spec, out)

    v = subprocess.run([sys.executable, os.path.join(HERE, 'verify_cartridge.py'), out, '--json',
                        '--expect-items', str(rep['items'])], capture_output=True, text=True, encoding='utf-8')
    try:
        verify = json.loads(v.stdout)
    except json.JSONDecodeError:
        print(v.stdout, v.stderr); raise
    if not verify['ok']:
        os.remove(out)
        print(json.dumps(verify, indent=1))
        sys.exit('verification FAILED; cartridge removed')

    mods = []
    for m in spec['modules']:
        mods.append({'id': m['id'], 'title': m['title'], 'gid': rep['module_ids'][m['id']],
                     'published': bool(m.get('published', True)), 'items': len(m.get('items', []))})
    counts = {k: rep[k] for k in ('pages', 'assignments', 'quizzes', 'discussions', 'files', 'modules', 'items')}
    weights = [{'title': g['title'], 'weight': g.get('weight', 0)} for g in spec.get('assignment_groups', [])]
    pr = spec.get('pull_report') or {}
    side = {
        'id': kit, 'label': label, 'code': spec['course'].get('code'), 'title': spec['course']['title'],
        'file': 'cartridges/%s.imscc' % kit, 'bytes': rep['bytes'], 'version': version,
        'built': datetime.datetime.now().isoformat(timespec='seconds'),
        'front_page': rep['front_page'], 'items': rep['items'], 'modules': mods, 'counts': counts, 'weights': weights,
        'weighted': any(float(w['weight'] or 0) > 0 for w in weights),
        'source': ('Canvas course %s on %s, pulled %s' % (pr.get('course_id'), pr.get('host', '').replace('https://', ''), spec['course'].get('date')))
                  if pr else 'spec %s' % os.path.basename(spec_path),
        'verify': {'ok': True, 'warnings': verify['warnings'], 'stats': verify['stats']},
        'status': 'ready',
    }
    with open(os.path.join(ROOT, 'cartridges', kit + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(side, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: side[k] for k in ('id', 'file', 'bytes', 'items', 'front_page', 'counts')}, indent=1))
    for w in verify['warnings']:
        print('WARN', w)


if __name__ == '__main__':
    main()
