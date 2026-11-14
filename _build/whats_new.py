"""New modules on the Optimizer home page.

Reads the published store (catalog.json and each ready kit's sidecar), remembers the day
each module was first seen, and writes whatsnew.json for index.html to list.

Nothing in the store is read for dates and nothing in the store is changed: the record of
what has been seen lives here, in whatsnew/seen.json. The first run records everything
already in the store as seen with no date, so the list starts empty and fills from then on.

    python _build/whats_new.py                 # read the live store
    python _build/whats_new.py --store DIR     # read a local checkout of the store
    python _build/whats_new.py --today 2026-12-01 --dry-run

A module is listed under its unit. Kits that already name units ("Module 4: Robin Hood -
Week 1") use them, the way the module list in index.html does. Kits built week by week
with no unit above the week take their units from whatsnew/groups.json; a week that is
not in that file lists under its own title.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = 'https://optimaondemand.github.io/optima-courses-2026-27/'
SEEN = os.path.join(ROOT, 'whatsnew', 'seen.json')
GROUPS = os.path.join(ROOT, 'whatsnew', 'groups.json')
OUT = os.path.join(ROOT, 'whatsnew.json')
KEEP_DAYS = 45          # whatsnew.json carries this many days; the page shows the last 14

WEEK = re.compile(r'\bWeek\s+0*(\d+)', re.I)
QUARTER = re.compile(r'\bQ([1-4])\b')
UNIT_NUM = re.compile(r'^\s*(?:Module|Unit)\s+(\d+[A-Z]?)\b', re.I)
# Modules that are not course content: never listed, never counted.
NOT_CONTENT = re.compile(
    r'^\s*start here|teacher|do not publish|appendi|back matter|front matter|course resources'
    r'|encyclopedia|vr tools|ambassador|course introduction|supplemental'
    r'|\bexams?\b|\bfinals\b|^\s*final\b|semester final|course review', re.I)
SKIP_CODES = {'9999999'}  # the mid-build test course


def read_json(store, path):
    if re.match(r'^https?://', store):
        req = urllib.request.Request(store + path, headers={'User-Agent': 'optima-course-kit'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    with open(os.path.join(store, path), encoding='utf-8') as f:
        return json.load(f)


def is_sparkle(kit):
    return kit.get('edition') == 'sparkle' or kit['id'].endswith('-sparkle')


# Courses whose weekly modules are all Sparkle builds (same list as SPARKLE_COURSES in index.html).
SPARKLE_COURSES = re.compile(r'^(2002040|2002070|2002100)-')


def module_key(kit_id, mod):
    """A key that survives a retitled week: the unit and week numbers when the title has them."""
    title = mod.get('title') or ''
    wk, q, un = WEEK.search(title), QUARTER.search(title), UNIT_NUM.match(title)
    if wk:
        return '%s|%s%sW%s' % (kit_id, 'M%s' % un.group(1).upper() if un else '', 'Q%s' % q.group(1) if q else '', wk.group(1))
    return '%s|%s' % (kit_id, mod.get('id') or title)


def unit_of(kit, mod, groups):
    """The unit a module is listed under."""
    if is_sparkle(kit):
        return kit.get('unit') or kit.get('label') or kit['id']
    title = (mod.get('title') or '').strip()
    wk, q, un = WEEK.search(title), QUARTER.search(title), UNIT_NUM.match(title)
    if un and wk:   # "Module 4: Robin Hood - Week 1" -> "Module 4: Robin Hood"
        return re.sub(r'\s*[·–—:,-]?\s*Week\s+\d+.*$', '', title, flags=re.I).strip() or title
    if wk:
        for g in groups.get(kit['id'], []):
            if int(wk.group(1)) in g['weeks'] and ('q' not in g or (q and int(q.group(1)) == g['q'])):
                return g['unit']
    return title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--store', default=STORE)
    ap.add_argument('--today')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    store = a.store if re.match(r'^https?://', a.store) else os.path.abspath(a.store)
    if re.match(r'^https?://', store) and not store.endswith('/'):
        store += '/'
    today = a.today or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)).strftime('%Y-%m-%d')

    groups = json.load(open(GROUPS, encoding='utf-8')).get('kits', {}) if os.path.exists(GROUPS) else {}
    first_run = not os.path.exists(SEEN)
    ledger = {'since': today, 'seen': {}} if first_run else json.load(open(SEEN, encoding='utf-8'))
    seen = ledger['seen']

    catalog = read_json(store, 'catalog.json')
    rows, failed = {}, []
    for course in catalog.get('courses', []):
        if str(course.get('code')) in SKIP_CODES:
            continue
        for kit in course.get('kits', []):
            if kit.get('status') != 'ready' or not kit.get('sidecar'):
                continue
            try:
                mods = read_json(store, kit['sidecar']).get('modules', [])
            except Exception as e:      # a kit that cannot be read is retried on the next run
                failed.append('%s: %s' % (kit['id'], e))
                continue
            for mod in mods:
                if NOT_CONTENT.search(mod.get('title') or ''):
                    continue
                key = module_key(kit['id'], mod)
                if key not in seen:
                    seen[key] = '' if first_run else today
                date = seen[key]
                if not date:
                    continue
                unit = unit_of(kit, mod, groups)
                row = rows.setdefault((date, kit['id'], unit), {
                    'date': date, 'code': str(course.get('code')), 'course': course.get('title'),
                    'grade': str(course.get('grade') or ''), 'subject': course.get('subject') or '',
                    'kit': kit['id'], 'unit': unit, 'modules': 0,
                    'sparkle': is_sparkle(kit) or bool(SPARKLE_COURSES.match(kit['id']) and WEEK.search(mod.get('title') or ''))})
                row['modules'] += 1

    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    units = sorted((r for r in rows.values() if r['date'] >= cutoff),
                   key=lambda r: (r['date'], r['course'], r['kit'], r['unit']))
    units.sort(key=lambda r: r['date'], reverse=True)
    out = {'since': ledger['since'], 'units': units}

    print('store: %s' % store)
    print('modules on record: %d%s' % (len(seen), ' (first run: all recorded as already there)' if first_run else ''))
    print('units in whatsnew.json: %d' % len(units))
    for f in failed:
        print('could not read ' + f, file=sys.stderr)
    if a.dry_run:
        print(json.dumps(out, indent=1, ensure_ascii=False)[:4000])
        return
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'since': ledger['since'], 'seen': dict(sorted(seen.items()))}, f, indent=0, ensure_ascii=False)
        f.write('\n')
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write('\n')


if __name__ == '__main__':
    main()
