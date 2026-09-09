"""pull_canvas.py - read a live Canvas course into a cc.py spec (READ-ONLY).

The deployed course is the naming authority, so titles, item order, points and
groups come from Canvas, not from the build folder. Nothing here writes to Canvas.

usage: pull_canvas.py <course_id> <cpalms_code> <out spec.json> [--files-dir DIR]
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HOST = 'https://optimaoaoteam.instructure.com'
TOKEN_FILE = r"C:/Users/JessicaDrexel/OneDrive - OptimaEd/Academic Design & Curriculum/Access tokens.txt"

QTYPE = {
    'multiple_choice_question': 'multiple_choice', 'true_false_question': 'true_false',
    'multiple_answers_question': 'multiple_answers', 'short_answer_question': 'short_answer',
    'essay_question': 'essay', 'file_upload_question': 'file_upload', 'text_only_question': 'text_only',
}


def token():
    with open(TOKEN_FILE, encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            m = re.search(r'\b([0-9]+~[A-Za-z0-9]+)', line)
            if m:
                return m.group(1)
    raise SystemExit('no Canvas token found in ' + TOKEN_FILE)


TOK = token()


def get(path, params=None, raw=False):
    url = path if path.startswith('http') else HOST + '/api/v1' + path
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOK})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
                if raw:
                    return data, r.headers
                return json.loads(data), r.headers
        except Exception as e:  # noqa: BLE001 - retry any transport failure with backoff
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
            sys.stderr.write('  retry %d for %s (%s)\n' % (attempt + 1, url[:90], e))


def paged(path, params=None):
    params = dict(params or {})
    params.setdefault('per_page', 100)
    out = []
    url = path
    while url:
        data, headers = get(url, params if url == path else None)
        out.extend(data)
        nxt = None
        for part in (headers.get('Link') or '').split(','):
            if 'rel="next"' in part:
                nxt = part[part.find('<') + 1:part.find('>')]
        url = nxt
    return out


def main():
    argv = sys.argv[1:]
    files_dir = None
    if '--files-dir' in argv:
        i = argv.index('--files-dir')
        files_dir = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith('--')]
    if len(args) != 3:
        print(__doc__)
        sys.exit(2)
    course_id, code, out = args
    cid = '/courses/%s' % course_id

    course, _ = get(cid, {'include[]': 'syllabus_body'})
    print('course:', course['name'], '| default_view', course.get('default_view'))
    groups = paged(cid + '/assignment_groups')
    spec = {
        'course': {'title': course['name'], 'code': code, 'default_view': course.get('default_view', 'wiki'),
                   'canvas_id': course['id'], 'canvas_code': course.get('course_code'),
                   'weighted': course.get('apply_assignment_group_weights', False)},
        'assignment_groups': [{'id': 'ag%d' % g['id'], 'title': g['name'], 'weight': g.get('group_weight') or 0,
                               'canvas_id': g['id']} for g in sorted(groups, key=lambda g: g['position'])],
        'rubrics': [], 'pages': [], 'assignments': [], 'quizzes': [], 'discussions': [], 'files': [], 'modules': [],
        'syllabus_html': course.get('syllabus_body') or '',
    }
    gmap = {g['id']: 'ag%d' % g['id'] for g in groups}
    seen = {'page': {}, 'assignment': {}, 'quiz': {}, 'discussion': {}, 'file': {}}
    rubrics = {}
    unsupported = []

    def rubric_for(a):
        rs = a.get('rubric_settings')
        if not a.get('rubric') or not rs:
            return None
        rid = 'r%s' % rs['id']
        if rid not in rubrics:
            rubrics[rid] = {'id': rid, 'title': rs.get('title') or a['name'],
                            'free_form_comments': bool(rs.get('free_form_criterion_comments')),
                            'criteria': [{'description': c.get('description', ''), 'long_description': c.get('long_description', ''),
                                          'points': c.get('points', 0),
                                          'ratings': [{'description': r.get('description', ''), 'long_description': r.get('long_description', ''),
                                                       'points': r.get('points', 0)} for r in c.get('ratings', [])]}
                                         for c in a['rubric']]}
        return rid

    def add_page(url):
        if url in seen['page']:
            return seen['page'][url]
        p, _ = get(cid + '/pages/' + urllib.parse.quote(url, safe=''))
        pid = 'p_' + url
        spec['pages'].append({'id': pid, 'title': p['title'], 'slug': url, 'html': p.get('body') or '',
                              'front_page': bool(p.get('front_page')), 'published': bool(p.get('published'))})
        seen['page'][url] = pid
        return pid

    def add_assignment(aid):
        if aid in seen['assignment']:
            return seen['assignment'][aid]
        a, _ = get(cid + '/assignments/%s' % aid)
        sid = 'a%d' % a['id']
        spec['assignments'].append({'id': sid, 'title': a['name'], 'html': a.get('description') or '',
                                    'points': a.get('points_possible') or 0, 'grading_type': a.get('grading_type', 'points'),
                                    'submission_types': ','.join(a.get('submission_types') or ['none']),
                                    'group': gmap.get(a.get('assignment_group_id')), 'rubric': rubric_for(a),
                                    'rubric_use_for_grading': bool(a.get('use_rubric_for_grading')),
                                    'published': bool(a.get('published')),
                                    'allowed_extensions': ','.join(a.get('allowed_extensions') or []),
                                    'omit_from_final_grade': bool(a.get('omit_from_final_grade'))})
        seen['assignment'][aid] = sid
        return sid

    def add_quiz(qid):
        if qid in seen['quiz']:
            return seen['quiz'][qid]
        q, _ = get(cid + '/quizzes/%s' % qid)
        qs = paged(cid + '/quizzes/%s/questions' % qid)
        questions = []
        for qq in sorted(qs, key=lambda z: (z.get('position') or 0, z['id'])):
            t = QTYPE.get(qq['question_type'])
            if not t:
                unsupported.append((q['title'], qq['question_type']))
                continue
            answers = []
            for an in qq.get('answers') or []:
                answers.append({'text': an.get('html') or an.get('text') or '', 'correct': (an.get('weight') or 0) > 0,
                                'feedback': an.get('comments_html') or an.get('comments') or ''})
            questions.append({'type': t, 'text': qq.get('question_text') or '', 'points': qq.get('points_possible') or 0,
                              'answers': answers,
                              'feedback_correct': qq.get('correct_comments_html') or qq.get('correct_comments') or '',
                              'feedback_incorrect': qq.get('incorrect_comments_html') or qq.get('incorrect_comments') or '',
                              'feedback_general': qq.get('neutral_comments_html') or qq.get('neutral_comments') or ''})
        sid = 'q%d' % q['id']
        spec['quizzes'].append({'id': sid, 'title': q['title'], 'description': q.get('description') or '',
                                'quiz_type': q.get('quiz_type', 'assignment'), 'points': q.get('points_possible'),
                                'allowed_attempts': q.get('allowed_attempts', 1), 'shuffle_answers': bool(q.get('shuffle_answers')),
                                'show_correct_answers': bool(q.get('show_correct_answers', True)),
                                'group': gmap.get(q.get('assignment_group_id')), 'published': bool(q.get('published')),
                                'questions': questions, 'canvas_question_count': q.get('question_count')})
        seen['quiz'][qid] = sid
        return sid

    def add_discussion(did):
        if did in seen['discussion']:
            return seen['discussion'][did]
        d, _ = get(cid + '/discussion_topics/%s' % did)
        a = d.get('assignment') or {}
        sid = 'd%d' % d['id']
        spec['discussions'].append({'id': sid, 'title': d['title'], 'html': d.get('message') or '',
                                    'graded': bool(a), 'points': a.get('points_possible') or 0,
                                    'group': gmap.get(a.get('assignment_group_id')), 'published': bool(d.get('published')),
                                    'require_initial_post': bool(d.get('require_initial_post')),
                                    'discussion_type': d.get('discussion_type') or 'threaded',
                                    'rubric': rubric_for(a) if a else None})
        seen['discussion'][did] = sid
        return sid

    def add_file(fid):
        if fid in seen['file']:
            return seen['file'][fid]
        f, _ = get(cid + '/files/%s' % fid)
        name = f['display_name']
        path = name
        try:
            folder, _ = get('/folders/%s' % f['folder_id'])
            full = folder.get('full_name') or ''
            sub = full.split('/', 1)[1] if '/' in full else ''
            path = (sub + '/' + name) if sub else name
        except Exception:  # noqa: BLE001 - folder lookup is cosmetic
            pass
        if files_dir:
            local = os.path.join(files_dir, path.replace('/', os.sep))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            if not os.path.exists(local):
                data, _ = get(f['url'], raw=True)
                with open(local, 'wb') as fh:
                    fh.write(data)
            spec['files'].append({'path': path, 'src': os.path.abspath(local), 'canvas_id': f['id']})
        else:
            spec['files'].append({'path': path, 'src': None, 'canvas_id': f['id'], 'download_url': f['url']})
        seen['file'][fid] = path
        return path

    modules = paged(cid + '/modules')
    for m in sorted(modules, key=lambda z: z['position']):
        print('module:', m['name'], '(%d items)' % m['items_count'])
        items = paged(cid + '/modules/%d/items' % m['id'])
        mitems = []
        for it in sorted(items, key=lambda z: z['position']):
            t = it['type']
            base = {'title': it['title'], 'indent': it.get('indent', 0), 'published': bool(it.get('published', True))}
            if t == 'Page':
                mitems.append(dict(base, type='page', ref=add_page(it['page_url'])))
            elif t == 'Assignment':
                mitems.append(dict(base, type='assignment', ref=add_assignment(it['content_id'])))
            elif t == 'Quiz':
                mitems.append(dict(base, type='quiz', ref=add_quiz(it['content_id'])))
            elif t == 'Discussion':
                mitems.append(dict(base, type='discussion', ref=add_discussion(it['content_id'])))
            elif t == 'File':
                mitems.append(dict(base, type='file', ref=add_file(it['content_id'])))
            elif t == 'ExternalUrl':
                mitems.append(dict(base, type='url', url=it['external_url'], new_tab=bool(it.get('new_tab'))))
            elif t == 'SubHeader':
                mitems.append(dict(base, type='header'))
            else:
                unsupported.append((m['name'], 'module item type ' + t))
        spec['modules'].append({'id': 'm%d' % m['id'], 'title': m['name'], 'published': bool(m.get('published')),
                                'sequential': bool(m.get('require_sequential_progress')), 'items': mitems,
                                'canvas_id': m['id']})

    # the front page might not be a module item
    try:
        fp, _ = get(cid + '/front_page')
        if fp.get('url') and fp['url'] not in seen['page']:
            add_page(fp['url'])
    except Exception as e:  # noqa: BLE001
        print('no front page:', e)

    spec['rubrics'] = list(rubrics.values())
    spec['pull_report'] = {
        'host': HOST, 'course_id': course['id'], 'pulled_modules': len(spec['modules']),
        'items': sum(len(m['items']) for m in spec['modules']),
        'pages': len(spec['pages']), 'assignments': len(spec['assignments']), 'quizzes': len(spec['quizzes']),
        'discussions': len(spec['discussions']), 'files': len(spec['files']), 'rubrics': len(spec['rubrics']),
        'unsupported': unsupported,
        'quiz_question_gaps': [(q['title'], q['canvas_question_count'], len(q['questions'])) for q in spec['quizzes']
                               if q['canvas_question_count'] not in (None, 0) and q['canvas_question_count'] != len(q['questions'])],
    }
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(spec, fh, indent=1, ensure_ascii=False)
    print(json.dumps(spec['pull_report'], indent=1))


if __name__ == '__main__':
    main()
