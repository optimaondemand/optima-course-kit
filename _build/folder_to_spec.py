# -*- coding: utf-8 -*-
"""folder_to_spec.py - build a cc.py spec straight from a course build folder.

No Canvas in the loop. The recipe names the course folder, the module folders,
the GitHub Pages base the lesson pages live at, and the grading rules the course
states on its own pages. Parsing is delegated to the course's deploy harness
(common.classify, quizparse, mapparse, sequence.order_week, specs) so the kit and
the Canvas deploy read the same files the same way.

usage: folder_to_spec.py <recipe.json> <out spec.json>

Nothing may fall through: an unclassified source file, an unparsed quiz, an
ambiguous answer key, or a missing teacher file stops the build.
"""
import collections
import datetime
import io
import json
import os
import re
import sys

QTYPE = {'multiple_choice_question': 'multiple_choice', 'true_false_question': 'true_false',
         'multiple_answers_question': 'multiple_answers', 'short_answer_question': 'short_answer',
         'essay_question': 'essay', 'file_upload_question': 'file_upload', 'text_only_question': 'text_only'}
PER_Q = re.compile(r"\((\d+)\s*pts?\)", re.I)
HTMLCOMMENT = re.compile(r"<!--.*?-->", re.S)


def iframe(url, height):
    return ('<p><iframe src="%s" style="width:100%%;height:%dpx;border:none;" '
            'allowfullscreen="" title="Lesson content" loading="lazy"></iframe></p>' % (url, height))


def read(path):
    return io.open(path, encoding='utf-8', errors='replace').read()


def slug_id(prefix, mod, fname, C):
    return '%s_%s_%s' % (prefix, mod.lower(), os.path.splitext(C.slug(fname))[0])


def main(recipe_path, out_path):
    R = json.load(io.open(recipe_path, encoding='utf-8'))
    sys.path.insert(0, R['harness'])
    import common as C           # noqa: E402
    import quizparse             # noqa: E402
    import sequence              # noqa: E402
    import specs                 # noqa: E402
    import canvas as K           # noqa: E402  (rce_body only)
    import build_manifest as BM  # noqa: E402  (canvas_title, lesson_id_of)

    DEV = R['dev']
    root_course = os.path.dirname(DEV)
    problems = []
    extra = None
    if R.get('extra_module'):
        sys.path.insert(0, os.path.dirname(os.path.abspath(recipe_path)))
        extra = __import__(R['extra_module'])

    # ---------------------------------------------------------- classify
    recs = []
    for M in R['modules']:
        if M.get('shared') or M.get('files'):
            continue
        root = os.path.join(DEV, M['folder'])
        weeks = [d for d in os.listdir(root) if d.startswith('Week ')]
        last_week = max(int(d.split()[1]) for d in weeks) if weeks else 0
        for dp, dn, fns in os.walk(root):
            if ('__pycache__' in dp or os.sep + '_pdf' in dp or os.sep + '_build' in dp
                    or 'Class PowerPoints' in dp):
                continue
            for fn in sorted(fns):
                if not fn.lower().endswith(('.html', '.md')):
                    continue
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, root).replace('\\', '/')
                info = C.classify(rel, fn)
                if info is None:
                    info = C.classify_wrapper(rel, fn, M['key'], M['text'], last_week)
                if info is None and extra is not None:
                    info = extra.classify(rel, fn, M, last_week, R)
                if info is None:
                    problems.append('unclassified: %s :: %s' % (M['key'], rel))
                    continue
                if info.get('skip') or info['kind'] in R.get('skip_kinds', []):
                    # e.g. Semester 1 never listed the game pages as module items;
                    # the lessons link to them instead
                    continue
                info['module'] = M['key']
                info['module_folder'] = M['folder']
                info['gh_dir'] = M['gh_dir']
                info['abs'] = full
                info['fname'] = fn
                info['text'] = M['text']
                if info['kind'] == 'lesson':
                    info['lesson_id'] = BM.lesson_id_of(full)
                if not info.get('canvas_title'):
                    info['canvas_title'] = BM.canvas_title(info)
                if extra is not None and hasattr(extra, 'adjust'):
                    extra.adjust(info, M, R)
                if info['target'] == C.GITHUB_HOSTED:
                    info['url'] = R['pages_base'] + '/' + M['gh_dir'] + '/' + C.slug(fn)
                recs.append(info)
        if extra is not None and hasattr(extra, 'synthetic'):
            for info in extra.synthetic(M, last_week, R):
                recs.append(info)

    # ---------------------------------------------------------- sequence
    by_mod = collections.defaultdict(list)
    for r in recs:
        by_mod[r['module']].append(r)
    unplaced_report = []
    seq_by_mod = {}
    for M in R['modules']:
        if M.get('shared') or M.get('files'):
            continue
        mrecs = by_mod[M['key']]
        pre = sorted((r for r in mrecs if r['week'] is None and r['order'][1] < 0), key=lambda r: r['order'][1])
        post = sorted((r for r in mrecs if r['week'] is None and r['order'][1] > 0), key=lambda r: r['order'][1])
        seq = list(pre)
        for wk in sorted(set(r['week'] for r in mrecs if r['week'] is not None)):
            wrecs = [r for r in mrecs if r['week'] == wk]
            mp = [r for r in wrecs if r['kind'] == 'module-map']
            if not mp:
                problems.append('Module %s Week %d has no Module Map' % (M['key'], wk))
                seq.extend(sorted(wrecs, key=lambda r: r['order'][1]))
                continue
            ordered, unplaced = sequence.order_week(wrecs, mp[0]['abs'])
            # order_week appends anything the map never mentions to the end of the
            # week. A grammar lesson the map forgot belongs where the classifier's
            # own week order puts it, so slot each straggler before the first placed
            # record with a later classifier rank instead.
            placed = ordered[:len(ordered) - len(unplaced)]
            for u in unplaced:
                rank = u['order'][1]
                at = next((i for i, r in enumerate(placed) if r['order'][1] > rank), len(placed))
                placed.insert(at, u)
                unplaced_report.append('Module %-3s Week %d  %-16s %s' % (M['key'], wk, u['kind'], u['title'][:52]))
            seq.extend(placed)
        seq.extend(post)
        if extra is not None and hasattr(extra, 'place'):
            seq = extra.place(M, seq, R)
        seq_by_mod[M['key']] = seq

    # ---------------------------------------------------------- emit
    S = {'course': {'title': R['title'], 'code': R['code'], 'default_view': 'wiki', 'weighted': False},
         'assignment_groups': [{'id': 'ag1', 'title': 'Assignments', 'weight': 0}],
         'rubrics': [], 'pages': [], 'assignments': [], 'quizzes': [], 'discussions': [], 'files': [], 'modules': [],
         'source': {'recipe': os.path.basename(recipe_path), 'dev': DEV,
                    'built': datetime.datetime.now().isoformat(timespec='seconds')}}

    fp = R.get('front_page_html')
    if fp:
        body = HTMLCOMMENT.sub('', read(os.path.join(root_course, fp))).strip()
        S['pages'].append({'id': 'p_course-home', 'title': 'Course Home', 'html': body,
                           'front_page': True, 'published': True})

    POINTS = R['points']
    ATT_Q, ATT_S = R.get('quiz_attempts', 2), R.get('survey_attempts', 1)
    halves = R.get('project_rubric_half', ['Essay'])

    def points_for(rec):
        if 'points_override' in rec:
            return rec['points_override']
        if rec['kind'] == 'project':
            half = rec.get('half', '')
            essay = any(h in half for h in halves)
            return R['project_points']['essay'] if essay else R['project_points']['creative']
        if rec['kind'] in POINTS:
            return POINTS[rec['kind']]
        return rec.get('points', 10)

    for M in R['modules']:
        key = M['key']
        items = []
        if M.get('shared'):
            for sp in R['shared_pages']:
                pid = 'p_shared_' + os.path.splitext(C.slug(sp['title'] + '.x'))[0]
                if sp.get('gh'):
                    html = iframe(R['pages_base'] + '/' + sp['gh'], sp.get('height', 2200))
                else:
                    src = os.path.join(DEV, '_Course Shared', sp['local'])
                    raw = read(src)
                    html = specs.md_block(raw) if src.endswith('.md') else K.rce_body(raw)
                S['pages'].append({'id': pid, 'title': sp['title'], 'html': html, 'published': True})
                items.append({'type': 'page', 'ref': pid, 'title': sp['title'], 'published': True})
            S['modules'].append({'id': 'm_' + key, 'title': M['title'], 'published': M['published'], 'items': items})
            continue
        if M.get('files'):
            for tf in R['teacher_files']:
                src = os.path.join(root_course, tf['path'])
                if not os.path.exists(src):
                    problems.append('missing teacher file: %s' % src)
                    continue
                path = R['files_folder'] + '/' + os.path.basename(src)
                S['files'].append({'path': path, 'src': src})
                items.append({'type': 'file', 'ref': path, 'title': tf['title'], 'published': False})
            S['modules'].append({'id': 'm_' + key, 'title': M['title'], 'published': M['published'], 'items': items})
            continue

        pub = M['published']
        rubric_id = None
        rubric_rec = [r for r in seq_by_mod[key] if r['target'] == C.CANVAS_RUBRIC]
        if rubric_rec:
            rr = rubric_rec[0]
            p = specs.parse_rubric(rr['abs'])
            for w in p['warnings']:
                problems.append('rubric %s: %s' % (rr['file'], w))
            rubric_id = 'r_' + key.lower()
            crit = []
            for c in p['criteria']:
                ratings = [{'description': lv['name'], 'long_description': lv['long'], 'points': lv['points'] * 2.5}
                           for lv in sorted(c['levels'], key=lambda x: -x['points'])]
                crit.append({'description': c['name'], 'long_description': c['description'],
                             'points': 10, 'ratings': ratings})
            S['rubrics'].append({'id': rubric_id, 'title': '%s Rubric' % rr['canvas_title'], 'criteria': crit})

        for r in seq_by_mod[key]:
            t = r['target']
            title = r['canvas_title']
            if t == C.CANVAS_RUBRIC:
                continue
            if r.get('spec_rubric'):
                # a record that carries its own rubric (S1 forums, recordings)
                S['rubrics'].append(r['spec_rubric'])
            if t == C.GITHUB_HOSTED:
                pid = slug_id('p', key, r['fname'], C)
                h = R['iframe_h'].get(r['kind'], R['default_h'])
                S['pages'].append({'id': pid, 'title': title, 'html': iframe(r['url'], h), 'published': pub,
                                   'week': r['week'], 'kind': r['kind']})
                items.append({'type': 'page', 'ref': pid, 'title': title, 'published': pub, 'week': r['week']})
            elif t == C.CANVAS_ASSIGN:
                aid = slug_id('a', key, r['fname'], C)
                if 'html_override' in r:
                    html = r['html_override']
                else:
                    raw = read(r['abs'])
                    html = specs.md_block(raw) if r['ext'] == '.md' else K.rce_body(raw)
                a = {'id': aid, 'title': title, 'html': html, 'points': points_for(r), 'grading_type': 'points',
                     'submission_types': r.get('submission_types', 'online_upload,online_text_entry'),
                     'group': 'ag1', 'published': pub, 'week': r['week'], 'kind': r['kind']}
                if r['kind'] == 'project' and rubric_id and any(h in r.get('half', '') for h in halves):
                    a['rubric'] = rubric_id
                if r.get('spec_rubric'):
                    a['rubric'] = r['spec_rubric']['id']
                S['assignments'].append(a)
                items.append({'type': 'assignment', 'ref': aid, 'title': title, 'published': pub, 'week': r['week']})
            elif t == C.CANVAS_QUIZ:
                qid = slug_id('q', key, r['fname'], C)
                p = quizparse.parse(r['abs'])
                survey = r['kind'] in ('module-intro', 'module-outro')
                for w in p['warnings']:
                    # a survey's opinion questions have no right answer by design
                    if survey and 'correct answers' in w:
                        continue
                    problems.append('quiz %s: %s' % (r['file'], w))
                n = len(p['questions'])
                raw = read(r['abs'])
                vals = [int(v) for v in PER_Q.findall(raw)]
                if survey:
                    total = 0
                elif vals and len(set(vals)) == 1 and n:
                    total = vals[0] * n
                else:
                    total = p.get('points') or n or 8
                per = 0 if survey else round(float(total) / max(1, n), 4)
                hints = {int(m.group(1)): m.group(2).lower()
                         for m in re.finditer(r'^\*\*Q(\d+)[.:]?\s*\(([^)]*)\)', raw, re.M)}
                qs = []
                for qu in p['questions']:
                    hint = hints.get(qu.get('num'), '')
                    answers = [{'text': a['text'], 'correct': bool(a['correct']),
                                'feedback': a.get('comments', '')} for a in qu['answers']]
                    if (R.get('split_combined_questions') and answers
                            and 'multiple choice' in hint and 'short answer' in hint):
                        # "(Multiple choice + short answer)" was deployed as two
                        # Canvas questions: the choice, then an explanation
                        qs.append({'type': 'multiple_choice', 'text': qu['text'], 'points': per, 'answers': answers,
                                   'feedback_correct': '', 'feedback_incorrect': ''})
                        qs.append({'type': 'essay', 'text': '<p>Explain your choice above in two or three sentences.</p>',
                                   'points': per, 'answers': [], 'feedback_correct': '', 'feedback_incorrect': ''})
                        continue
                    qs.append({'type': QTYPE.get(qu['type'], 'essay'), 'text': qu['text'], 'points': per,
                               'answers': answers,
                               'feedback_correct': qu.get('correct_comments', ''),
                               'feedback_incorrect': qu.get('incorrect_comments', '')})
                S['quizzes'].append({'id': qid, 'title': title, 'description': p.get('description') or '',
                                     'quiz_type': 'survey' if survey else 'assignment', 'points': total,
                                     'allowed_attempts': ATT_S if survey else ATT_Q, 'shuffle_answers': not survey,
                                     'show_correct_answers': True, 'group': 'ag1', 'published': pub,
                                     'questions': qs, 'week': r['week'], 'kind': r['kind']})
                items.append({'type': 'quiz', 'ref': qid, 'title': title, 'published': pub, 'week': r['week']})
            elif t == C.CANVAS_DISC:
                did = slug_id('d', key, r['fname'], C)
                if 'html_override' in r:
                    body = r['html_override']
                else:
                    p = specs.parse_discussion(r['abs'])
                    for w in p['warnings']:
                        problems.append('discussion %s: %s' % (r['file'], w))
                    body = p['body']
                d = {'id': did, 'title': title, 'html': body, 'graded': True,
                     'points': points_for(r) if r['kind'] != 'module-discussion' else POINTS.get('module-discussion', 10),
                     'group': 'ag1', 'published': pub, 'require_initial_post': True,
                     'week': r['week'], 'kind': r['kind']}
                if r.get('spec_rubric'):
                    d['rubric'] = r['spec_rubric']['id']
                S['discussions'].append(d)
                items.append({'type': 'discussion', 'ref': did, 'title': title, 'published': pub, 'week': r['week']})
        S['modules'].append({'id': 'm_' + key, 'title': M['title'], 'published': pub, 'items': items})

    S['build_report'] = {'records': len(recs), 'unplaced_from_map': unplaced_report, 'problems': problems,
                         'by_kind': dict(collections.Counter(r['kind'] for r in recs))}
    json.dump(S, io.open(out_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('records %d | pages %d | assignments %d | quizzes %d (%d questions) | discussions %d | rubrics %d | files %d | modules %d'
          % (len(recs), len(S['pages']), len(S['assignments']), len(S['quizzes']),
             sum(len(q['questions']) for q in S['quizzes']), len(S['discussions']), len(S['rubrics']),
             len(S['files']), len(S['modules'])))
    for m in S['modules']:
        print('   %-64s %3d items' % (m['title'][:64], len(m['items'])))
    if unplaced_report:
        print('fell back to classifier order (%d):' % len(unplaced_report))
        for u in unplaced_report:
            print('   ', u)
    if problems:
        print('\n!!! PROBLEMS (%d):' % len(problems))
        for p in problems:
            print('   ', p)
        return 1
    print('wrote', out_path)
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
