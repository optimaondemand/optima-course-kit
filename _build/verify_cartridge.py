"""verify_cartridge.py - structural gate for a Canvas .imscc before anyone imports it.

Checks the things a Canvas import fails on silently or reports as a vague
"issue": dangling references, malformed XML, missing files, a missing or
duplicated front page, unresolved link tokens. Exit 1 on any failure.

usage: verify_cartridge.py file.imscc [--expect-items N] [--json]
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {'cp': 'http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1',
      'c': 'http://canvas.instructure.com/xsd/cccv1p0'}
KNOWN_ITEM_TYPES = {'WikiPage', 'Assignment', 'Quizzes::Quiz', 'DiscussionTopic', 'Attachment',
                    'ExternalUrl', 'ContextModuleSubHeader', 'ContextExternalTool'}
OBJ_REF = re.compile(r'\$CANVAS_OBJECT_REFERENCE\$/(assignments|quizzes|discussion_topics|modules|wiki_pages)/([A-Za-z0-9_-]+)')
WIKI_REF = re.compile(r'\$WIKI_REFERENCE\$/pages/([A-Za-z0-9._~-]+)')
FILE_REF = re.compile(r'\$IMS-CC-FILEBASE\$/([^"\'\s<>]+)')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    path = args[0]
    expect_items = int(sys.argv[sys.argv.index('--expect-items') + 1]) if '--expect-items' in sys.argv else None
    fails, warns, stats = [], [], {}
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    text = {}
    for n in names:
        if n.endswith(('.xml', '.html', '.qti', '.txt')):
            text[n] = z.read(n).decode('utf-8', errors='replace')

    # 1. every XML file is well-formed
    for n, t in text.items():
        if n.endswith(('.xml', '.qti')):
            try:
                ET.fromstring(t.encode('utf-8'))
            except ET.ParseError as e:
                fails.append('malformed XML %s: %s' % (n, e))
    if 'imsmanifest.xml' not in names:
        fails.append('no imsmanifest.xml')
        report(path, fails, warns, stats)
    man = ET.fromstring(text['imsmanifest.xml'].encode('utf-8'))

    # 2. resources: unique ids, every listed file exists
    res = {}
    for r in man.findall('.//cp:resources/cp:resource', NS):
        rid = r.get('identifier')
        if rid in res:
            fails.append('duplicate resource id %s' % rid)
        res[rid] = r
        for f in r.findall('cp:file', NS):
            if f.get('href') not in names:
                fails.append('resource %s lists missing file %s' % (rid, f.get('href')))
        if r.get('href') and r.get('href') not in names:
            fails.append('resource %s href missing %s' % (rid, r.get('href')))
        for d in r.findall('cp:dependency', NS):
            if d.get('identifierref') not in {x.get('identifier') for x in man.findall('.//cp:resource', NS)}:
                fails.append('resource %s depends on unknown %s' % (rid, d.get('identifierref')))
    stats['resources'] = len(res)
    by_type = {}
    for r in res.values():
        by_type[r.get('type')] = by_type.get(r.get('type'), 0) + 1
    stats['resource_types'] = by_type

    # 3. organization items resolve
    org_items = man.findall('.//cp:organization//cp:item[@identifierref]', NS)
    for it in org_items:
        if it.get('identifierref') not in res:
            fails.append('organization item %s -> unknown resource %s' % (it.get('identifier'), it.get('identifierref')))
    stats['organization_items'] = len(org_items)

    # 4. module_meta
    if 'course_settings/module_meta.xml' not in names:
        fails.append('no course_settings/module_meta.xml')
    else:
        mm = ET.fromstring(text['course_settings/module_meta.xml'].encode('utf-8'))
        mods = mm.findall('c:module', NS)
        stats['modules'] = len(mods)
        module_ids = {m.get('identifier') for m in mods}
        n_items, types = 0, {}
        for m in mods:
            positions = []
            for it in m.findall('c:items/c:item', NS):
                n_items += 1
                ct = it.findtext('c:content_type', '', NS)
                types[ct] = types.get(ct, 0) + 1
                positions.append(int(it.findtext('c:position', '0', NS)))
                if ct not in KNOWN_ITEM_TYPES:
                    fails.append('module %s item has unknown content_type %r' % (m.findtext('c:title', '', NS), ct))
                ref = it.findtext('c:identifierref', None, NS)
                if ct in ('WikiPage', 'Assignment', 'Quizzes::Quiz', 'DiscussionTopic', 'Attachment'):
                    if ref not in res:
                        fails.append('module item %r (%s) -> unknown resource %s' % (it.findtext('c:title', '', NS), ct, ref))
                if ct == 'ExternalUrl' and not it.findtext('c:url', '', NS):
                    fails.append('ExternalUrl item %r has no url' % it.findtext('c:title', '', NS))
                if not it.findtext('c:title', '', NS).strip():
                    fails.append('module item without a title in %s' % m.findtext('c:title', '', NS))
            if positions != sorted(positions) or len(set(positions)) != len(positions):
                fails.append('module %r item positions are not strictly increasing' % m.findtext('c:title', '', NS))
            elif positions != list(range(1, len(positions) + 1)):
                warns.append('module %r has gaps in item positions (a real export does this too)' % m.findtext('c:title', '', NS))
        stats['module_items'] = n_items
        stats['module_item_types'] = types
        if expect_items is not None and n_items != expect_items:
            fails.append('expected %d module items, found %d' % (expect_items, n_items))

    # 5. course settings + front page
    cs = text.get('course_settings/course_settings.xml', '')
    default_view = re.search(r'<default_view>([^<]*)', cs)
    default_view = default_view.group(1) if default_view else None
    stats['default_view'] = default_view
    wiki = [n for n in names if n.startswith('wiki_content/') and n.endswith('.html')]
    fronts = [n for n in wiki if 'name="front_page" content="true"' in text[n]]
    stats['pages'] = len(wiki)
    stats['front_page'] = fronts[0] if fronts else None
    if len(fronts) > 1:
        fails.append('more than one front page: %s' % fronts)
    if default_view == 'wiki' and not fronts:
        fails.append('default_view is wiki but no page is marked front_page')
    if fronts and default_view != 'wiki':
        warns.append('a front page exists but default_view is %r' % default_view)
    slugs = {n[len('wiki_content/'):-5] for n in wiki}
    for n in wiki:
        if 'name="identifier"' not in text[n]:
            fails.append('wiki page %s has no identifier meta' % n)

    # 6. assignment groups referenced exist; weights
    ag = text.get('course_settings/assignment_groups.xml', '')
    group_ids = set(re.findall(r'assignmentGroup identifier="([^"]+)"', ag))
    weights = [float(w) for w in re.findall(r'<group_weight>([^<]*)', ag)]
    stats['assignment_groups'] = len(group_ids)
    if '<group_weighting_scheme>percent' in cs and weights and abs(sum(weights) - 100) > 0.01:
        warns.append('weighted grading on but weights sum to %.1f' % sum(weights))
    refs = 0
    for n, t in text.items():
        for g in re.findall(r'<assignment_group_identifierref>([^<]+)', t):
            refs += 1
            if g not in group_ids:
                fails.append('%s references unknown assignment group %s' % (n, g))
    stats['group_refs'] = refs

    # 7. links: tokens resolved, object refs point at real things, file refs exist
    module_ids = set(re.findall(r'<module identifier="([^"]+)"', text.get('course_settings/module_meta.xml', '')))
    files_in_zip = {n[len('web_resources/'):] for n in names if n.startswith('web_resources/')}
    import urllib.parse
    for n, t in text.items():
        if n.endswith(('.html', '.xml', '.qti')):
            if re.search(r'\{\{[a-z]+(:[^}]*)?\}\}', t):
                fails.append('%s still contains a {{token}}' % n)
            for kind, ident in OBJ_REF.findall(t):
                if kind == 'modules':
                    if ident not in module_ids:
                        fails.append('%s links to unknown module %s' % (n, ident))
                elif ident not in res:
                    fails.append('%s links to unknown %s %s' % (n, kind, ident))
            for slug in WIKI_REF.findall(t):
                # Canvas writes either the page slug or the page's migration id here
                if slug not in slugs and slug not in res:
                    fails.append('%s links to unknown page slug %s' % (n, slug))
            for f in FILE_REF.findall(t):
                f = urllib.parse.unquote(f.split('?')[0])
                if f not in files_in_zip:
                    fails.append('%s references bundled file %s which is not in web_resources' % (n, f))

    # 8. quizzes: every assessment has a meta file and at least one item
    quiz_dirs = {n.split('/')[0] for n in names if n.endswith('/assessment_meta.xml')}
    stats['quizzes'] = len(quiz_dirs)
    empty = []
    for q in quiz_dirs:
        qti = text.get('non_cc_assessments/%s.xml.qti' % q) or text.get('%s/assessment_qti.xml' % q, '')
        if '<item ' not in qti:
            empty.append(q)
    if empty:
        warns.append('%d quiz(zes) have no questions' % len(empty))
    stats['assignments'] = len({n.split('/')[0] for n in names if n.endswith('/assignment_settings.xml')})
    stats['discussions'] = sum(1 for n, t in text.items() if '<topicMeta ' in t)
    stats['files'] = len(files_in_zip)
    pts = [float(p) for n, t in text.items() if n.endswith('assignment_settings.xml') or n.endswith('assessment_meta.xml') or '<topicMeta' in t
           for p in re.findall(r'<points_possible>([^<]*)', t)]
    stats['points_listed'] = round(sum(pts), 1)

    # 9. language gates (warn only - content may be pulled from a live course)
    fac = sum(len(re.findall(r'facilitator', t, re.I)) for n, t in text.items() if n.endswith('.html') or '<topic ' in t or '.qti' in n)
    if fac:
        warns.append('"facilitator" appears %d time(s) in student-facing text' % fac)

    report(path, fails, warns, stats)


def report(path, fails, warns, stats):
    out = {'file': path, 'ok': not fails, 'fails': fails, 'warnings': warns, 'stats': stats}
    if '--json' in sys.argv:
        print(json.dumps(out, indent=1))
    else:
        print('VERIFY', path)
        for k, v in stats.items():
            print('  %-20s %s' % (k, v))
        for w in warns:
            print('  WARN', w)
        for f in fails:
            print('  FAIL', f)
        print('  RESULT', 'PASS' if not fails else 'FAIL (%d)' % len(fails))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
