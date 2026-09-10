"""build_kit.py - spec.json -> cartridges/<kit>.imscc + cartridges/<kit>.json sidecar.

The sidecar is what the Course Kit widget reads (through catalog.json): where the
front page lives inside the zip, the module identifiers a home page can link to,
counts, weights, and the verify result. A kit that fails verification is deleted
so it can never be published half-built.

usage: build_kit.py <spec.json> <kit-id> --label "Semester 1" [--version YYYY.MM.DD] [--root DIR]
DIR (or $KIT_ROOT) is the cartridge repo root holding cartridges/; default = this repo.
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


FRONT_PAGE_PLACEHOLDER = (
    '<h2>Course Home</h2>'
    '<p>Your teacher will customize this page. Until then, start with '
    '<a href="{{modules}}">the module list</a>.</p>'
)


def ensure_front_page(spec):
    """Every kit needs exactly one front page: it is what the Course Kit widget
    swaps the teacher's home page into. A source course whose home view is
    Modules (or that never marked a page front_page) gets a placeholder page,
    and the course is told to open on it."""
    pages = spec.setdefault('pages', [])
    fronts = [p for p in pages if p.get('front_page')]
    if not fronts:
        ids = {p['id'] for p in pages}
        pid, n = 'p_course-home', 2
        while pid in ids:
            pid = 'p_course-home-%d' % n; n += 1
        pages.insert(0, {'id': pid, 'title': 'Course Home', 'html': FRONT_PAGE_PLACEHOLDER,
                         'front_page': True, 'published': True})
        print('NOTE source course had no front page; added a placeholder Course Home page')
    if spec['course'].get('default_view') != 'wiki':
        print('NOTE default_view was %r; set to wiki so the course opens on the home page' % spec['course'].get('default_view'))
        spec['course']['default_view'] = 'wiki'


def main():
    argv = sys.argv[1:]
    label, version = 'Semester 1', datetime.date.today().strftime('%Y.%m.%d')
    if '--label' in argv:
        i = argv.index('--label'); label = argv[i + 1]; del argv[i:i + 2]
    if '--version' in argv:
        i = argv.index('--version'); version = argv[i + 1]; del argv[i:i + 2]
    global ROOT
    if '--root' in argv:
        i = argv.index('--root'); ROOT = os.path.abspath(argv[i + 1]); del argv[i:i + 2]
    elif os.environ.get('KIT_ROOT'):
        ROOT = os.path.abspath(os.environ['KIT_ROOT'])
    if len(argv) != 2:
        print(__doc__); sys.exit(2)
    spec_path, kit = argv
    with open(spec_path, encoding='utf-8') as fh:
        spec = json.load(fh)
    spec['course']['version'] = version
    spec['course']['date'] = datetime.date.today().isoformat()
    ensure_front_page(spec)
    out = os.path.join(ROOT, 'cartridges', kit + '.imscc')
    rep = cc.build(spec, out)
    if not rep.get('front_page'):
        os.remove(out)
        sys.exit('kit has no front page after build; cartridge removed')

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
    G = cc.Cartridge(spec).G
    groups = [{'id': G('group', g['id']), 'title': g['title'], 'weight': float(g.get('weight') or 0), 'position': i}
              for i, g in enumerate(spec.get('assignment_groups', []), 1)]
    for m in mods:
        m['xml'] = 'course_settings/module_meta.xml'
    settings = {'course_settings': 'course_settings/course_settings.xml',
                'assignment_groups': 'course_settings/assignment_groups.xml',
                'module_meta': 'course_settings/module_meta.xml',
                'date_format': 'YYYY-MM-DDTHH:MM:SS in UTC, no zone suffix (as Canvas exports write it)'}
    pr = spec.get('pull_report') or {}
    side = {
        'id': kit, 'label': label, 'code': spec['course'].get('code'), 'title': spec['course']['title'],
        'file': 'cartridges/%s.imscc' % kit, 'bytes': rep['bytes'], 'version': version,
        'built': datetime.datetime.now().isoformat(timespec='seconds'),
        'front_page': rep['front_page'], 'items': rep['items'], 'modules': mods, 'counts': counts, 'weights': weights,
        'groups': groups, 'graded_items': rep['index'], 'settings': settings,
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
