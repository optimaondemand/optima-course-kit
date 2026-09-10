# -*- coding: utf-8 -*-
"""Semester 1 (7th ELA) additions to the Semester 2 harness classifier.

Semester 1 was deployed to Canvas course 2 in July 2026 by an earlier script and
then received twelve more instruments in August (two All-Class Forums and two
imitative-genre recordings per module, from _Course Shared/_build). Its titles
and points differ from Semester 2 in five ways, all read off the live course:

  * the weekly quiz keeps its weekday: "Week N Friday Check-up"
  * Quick Writes are 10 points, not 15
  * both project halves carry 40 points and the rubric; Module 3 has one project
  * the Reading Journal has a mid-module check as well as the end check
  * work-session titles use a colon: "Week 8 — Work Session 1: Title"

Hooks used by folder_to_spec.py: classify, adjust, synthetic, place.
"""
import os
import re
import sys

RE_FORUM = re.compile(r"^All-Class Forum (\d+)\b")
RE_RECORDING = re.compile(r"^(Voyage Documentary|Field Dispatch|Podcast Episode) (\d+)$")

_inst = None


def instruments(R):
    """deploy_instruments7 + content7 + brand7, imported once from the course folder."""
    global _inst
    if _inst is None:
        sys.path.insert(0, R['instruments_harness'])
        import deploy_instruments7 as D  # noqa: E402
        import content7 as C7            # noqa: E402
        _inst = (D, C7)
    return _inst


def rubric_spec(rid, title, rows):
    crit = []
    for name, pts, full, part, no in rows:
        ratings = [{'description': 'Full credit', 'long_description': full, 'points': pts}]
        if part:
            ratings.append({'description': 'Partial', 'long_description': part, 'points': round(pts / 2.0)})
        ratings.append({'description': 'No credit', 'long_description': no, 'points': 0})
        crit.append({'description': name, 'long_description': '', 'points': pts, 'ratings': ratings})
    return {'id': rid, 'title': title, 'criteria': crit, 'free_form_comments': True}


def classify(rel, fname, M, last_week, R):
    """Forums and recordings: the .md beside the module is a spec written by the
    generator; the deployed body is rendered from content7, exactly as Canvas has it."""
    stem, ext = os.path.splitext(fname)
    D, C7 = instruments(R)
    num = M['num']
    m = RE_FORUM.match(stem)
    if m:
        n = int(m.group(1))
        f = [f for f in C7.FORUMS if f['module'] == num and f['n'] == n]
        if not f:
            return None
        f = f[0]
        return dict(kind='forum', target='discussion', title=f['name'], canvas_title=f['name'], week=None,
                    file=rel, ext=ext, order=('mod', 500 + n), html_override=D.forum_body(f),
                    points_override=25, after=f['after_item'],
                    spec_rubric=rubric_spec('r_%s_forum%d' % (M['key'], n), 'All-Class Forum', f['rubric']))
    m = RE_RECORDING.match(stem)
    if m:
        n = int(m.group(2))
        r = [r for r in C7.RECORDINGS if r['module'] == num and r['n'] == n]
        if not r:
            return None
        r = r[0]
        return dict(kind='recording', target='assignment', title=r['name'], canvas_title=r['name'], week=None,
                    file=rel, ext=ext, order=('mod', 520 + n), html_override=D.recording_body(r),
                    points_override=25, submission_types='media_recording,online_upload', after=r['after_item'],
                    spec_rubric=rubric_spec('r_%s_rec%d' % (M['key'], n), C7.GENRES[num]['item_name'],
                                            C7.RECORDING_RUBRIC))
    return None


def adjust(info, M, R):
    """Semester 1 title and points conventions, read off Canvas course 2."""
    k = info['kind']
    if k == 'check-up' and R.get('checkup_title'):
        info['canvas_title'] = R['checkup_title'] % info['week']
    elif k == 'work-session' and R.get('work_session_title'):
        m = re.match(r"^Work Session (\d+) — (.+)$", info['title'])
        if m:
            info['canvas_title'] = R['work_session_title'] % (info['week'], m.group(1), m.group(2))
    elif k == 'project':
        half = re.sub(r"\s*\(.*?\)\s*", "", info.get('half', '')).strip()
        if M.get('single_project_title'):
            info['canvas_title'] = M['single_project_title']
        else:
            info['canvas_title'] = '%s Final Project — %s' % (M['abbr'], half)
    elif k == 'journal-check' and M.get('journal_end_week') and not info.get('_mid'):
        # the check closes the READING, which ends a week before the project week
        info['canvas_title'] = 'Reading Journal Check — End of Module (Week %d)' % M['journal_end_week']
    return info


def _journal_check_body(M, R):
    import specs  # the harness is already on sys.path
    d = os.path.join(R['dev'], M['folder'], 'Module Wrappers and Project')
    for fn in os.listdir(d):
        if fn.startswith('Reading Journal Check') and fn.endswith('.md'):
            return specs.md_block(open(os.path.join(d, fn), encoding='utf-8', errors='replace').read())
    return '<p>Submit your Reading Journal.</p>'


def synthetic(M, last_week, R):
    """The mid-module Reading Journal Check exists in Canvas but has no file of its
    own: the one checkpoint spec covers both occurrences."""
    out = []
    wk = M.get('journal_mid_week')
    if wk:
        out.append(dict(kind='journal-check', target='assignment', week=None, file='(synthetic)', ext='.md',
                        title='Reading Journal Check', canvas_title='Reading Journal Check — Mid-Module (Week %d)' % wk,
                        order=('mod', 890), module=M['key'], module_folder=M['folder'], gh_dir=M['gh_dir'],
                        fname='Reading Journal Check Mid.md', text=M['text'], abs=None,
                        html_override=_journal_check_body(M, R), points_override=R['points']['journal-check'], _mid=True))
    return out


def place(M, seq, R):
    """Insert each named record directly after its anchor, in recipe order."""
    def find(pred):
        for i, r in enumerate(seq):
            if pred(r):
                return i
        return None
    for pl in M.get('placements', []):
        mt, at = pl['match'], pl['after']
        i = find(lambda r: mt in r['canvas_title'])
        if i is None:
            print('   !! placement: no record matching %r in module %s' % (mt, M['key']))
            continue
        rec = seq.pop(i)
        j = find(lambda r: at in r['canvas_title'])
        if j is None:
            print('   !! placement: anchor %r not found in module %s; appended' % (at, M['key']))
            seq.append(rec)
        else:
            seq.insert(j + 1, rec)
            if rec.get('week') is None:
                # inherit the anchor's week so the widget can propose a due date
                wk = seq[j].get('week')
                if wk is None:
                    mw = re.search(r'Week (\d+)', seq[j]['canvas_title'])
                    wk = int(mw.group(1)) if mw else None
                rec['week'] = wk
    # project halves in the order the live course lists them
    order = R.get('project_half_order')
    if order:
        idx = [i for i, r in enumerate(seq) if r['kind'] == 'project']
        if len(idx) > 1:
            def rank(r):
                for n, key in enumerate(order):
                    if key in r.get('half', ''):
                        return n
                return len(order)
            halves = sorted((seq[i] for i in idx), key=rank)
            for i, r in zip(idx, halves):
                seq[i] = r
    return seq
