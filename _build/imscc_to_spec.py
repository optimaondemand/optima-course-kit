# -*- coding: utf-8 -*-
"""imscc_to_spec.py - a Canvas-flavoured .imscc -> a Course Kit spec for optima-courses-2026-27.

For courses whose build pipeline already produces a Canvas cartridge (Hope, Discovering
CS, Digital Discoveries 6, Drivers Ed, the Mission: Move! PE courses), the cartridge is
the authoritative deployed structure. This reads it back into the spec contract
(optima-courses-2026-27/docs/SPEC.md): modules and items in cartridge order, pages,
assignments, quizzes (QTI 1.2 -> questions), discussions, external links, headers,
bundled files; publish state, points, groups and weights as shipped.

usage: imscc_to_spec.py <recipe.json>

Recipe (JSON):
  cartridge      path to the .imscc
  code, kit      CPALMS code and kit id (<code>-s1 | -s2 | -full ...)
  course_title   Canvas course title written into the spec
  store          path of the optima-courses-2026-27 checkout (default: sibling of this repo)
  course         {"title", "grade", "subject", "owner", "label"}: registers courses/<code>/course.json
                 (created if absent) and adds this kit with "label" to its kits list
  modules        {"select": [1-based indexes after skipping], "skip_titles": [regex...]}; default all
  drop_items     [regex on item title] items to leave out
  weeks          {"mode": "title" | "list" | "none", "per_module": 2, "starts": [...], "relative": true}
                 title: "Week N" in the item title, else the last week seen in the module, else
                        base + per_module*(module index); list: starts[i] per selected module;
                 relative: renumber so the first week of the kit is week 1
  completion     true -> pages must_mark_done, assignments/quizzes must_submit, discussions must_contribute
  front_page     regex on page title to mark as the front page when the cartridge marks none
  media          {"mode": "pack" | "error", "pack_out": DIR}: what to do with $IMS-CC-FILEBASE$ media.
                 pack: the HTML links the file BY PATH (course files/<folder>/<file>) and the media
                 travel in a files-only companion cartridge <pack_out>/<kit>-media-pack.imscc that the
                 teacher imports into the same course (the art-pack pattern; the public kit holds no media)
  replace        [[regex, replacement], ...] applied to every HTML body
  rename_groups  {"cartridge group title": "new title"}
  note           provenance sentence for spec.source

Nothing is invented: an item whose resource cannot be read, a question type the spec does
not support, or an unresolvable link stops the build with the reason.
"""
import html as html_lib
import io
import json
import os
import re
import shutil
import sys
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

QTYPE = {
    'multiple_choice_question': 'multiple_choice', 'true_false_question': 'true_false',
    'multiple_answers_question': 'multiple_answers', 'short_answer_question': 'short_answer',
    'essay_question': 'essay', 'file_upload_question': 'file_upload', 'text_only_question': 'text_only',
}
CC_PROFILE = {
    'cc.multiple_choice.v0p1': 'multiple_choice_question', 'cc.true_false.v0p1': 'true_false_question',
    'cc.multiple_response.v0p1': 'multiple_answers_question', 'cc.fib.v0p1': 'short_answer_question',
    'cc.essay.v0p1': 'essay_question',
}
FIGURE_SRC = '$CANVAS_COURSE_REFERENCE$/file_contents/course%20files/'
FILEBASE = re.compile(r'\$IMS-CC-FILEBASE\$/([^"\'\s<>]+)')
WIKIREF = re.compile(r'\$WIKI_REFERENCE\$/pages/([A-Za-z0-9\-_%.]+)')
OBJREF = re.compile(r'\$CANVAS_OBJECT_REFERENCE\$/(assignments|quizzes|discussion_topics|pages|modules)/([A-Za-z0-9_\-]+)')
COURSEREF = re.compile(r'\$CANVAS_COURSE_REFERENCE\$/(modules|assignments|grades|announcements|syllabus)(?![A-Za-z0-9_/])')
WEEK = re.compile(r'\bWeeks?\s+(\d+)', re.I)
TYPE_QTI = 'imsqti_xmlv1p2/imscc_xmlv1p1/assessment'
TYPE_DT = 'imsdt_xmlv1p1'


def strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    return root


def parse_xml(data):
    return strip_ns(ET.fromstring(data))


def slug(s, n=60):
    s = re.sub(r'&[a-z]+;|&#\d+;', ' ', html_lib.unescape(s or ''))
    s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
    return re.sub(r'-+', '-', s)[:n].strip('-') or 'x'


def t(el, tag, default=''):
    if el is None:
        return default
    v = el.findtext(tag)
    return default if v is None else v.strip()


def tb(el, tag, default=False):
    v = t(el, tag, None)
    return default if v is None or v == '' else v.lower() == 'true'


def num(v, default=0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f == int(f) else f


def inner_body(doc):
    m = re.search(r'<body[^>]*>(.*)</body>', doc, re.S | re.I)
    return (m.group(1) if m else doc).strip()


# ---------------------------------------------------------------- QTI -> questions
def qti_questions(xml_text, where, notes):
    root = parse_xml(xml_text.encode('utf-8'))
    assess = root.find('.//assessment')
    if assess is None:
        raise SystemExit('%s: no <assessment> in QTI' % where)
    meta = {t(f, 'fieldlabel'): t(f, 'fieldentry') for f in assess.findall('./qtimetadata/qtimetadatafield')}
    questions = []
    for item in assess.iter('item'):
        imeta = {t(f, 'fieldlabel'): t(f, 'fieldentry') for f in item.findall('./itemmetadata/qtimetadata/qtimetadatafield')}
        qt = imeta.get('question_type')
        if not qt:
            # plain Common Cartridge profile instead of Canvas metadata
            qt = CC_PROFILE.get((imeta.get('cc_profile') or '').strip())
        if qt not in QTYPE:
            raise SystemExit('%s: unsupported question type %r (item %s)' % (where, qt, item.get('ident')))
        q = {'type': QTYPE[qt], 'text': (item.findtext('./presentation/material/mattext') or '').strip(),
             'points': num(imeta.get('points_possible'), 1)}
        labels = [(rl.get('ident'), (rl.findtext('./material/mattext') or '').strip())
                  for rl in item.findall('./presentation/response_lid/render_choice/response_label')]
        fb = {f.get('ident'): (f.findtext('./flow_mat/material/mattext') or '').strip() for f in item.findall('itemfeedback')}
        correct, wrong, ans_fb, incorrect_fb, general_fb, correct_fb, sa = set(), set(), {}, None, None, None, []
        for rc in item.findall('./resprocessing/respcondition'):
            cv = rc.find('conditionvar')
            if cv is None:
                continue
            scored = any(num((sv.text or '0').strip(), 0) > 0 for sv in rc.findall('setvar'))
            links = [d.get('linkrefid') for d in rc.findall('displayfeedback')]
            direct = [v.text.strip() for v in cv.findall('varequal') if v.text] + [v.text.strip() for v in cv.findall('and/varequal') if v.text]
            negated = [v.text.strip() for v in cv.findall('not/varequal') if v.text] + [v.text.strip() for v in cv.findall('and/not/varequal') if v.text]
            if scored:
                correct.update(direct)
                wrong.update(negated)
                if q['type'] == 'short_answer':
                    sa.extend(direct)
                for ln in links:
                    if fb.get(ln) and not labels:
                        correct_fb = fb[ln]
            for v in direct:
                for ln in links:
                    if fb.get(ln):
                        ans_fb.setdefault(v, fb[ln])
            if cv.find('other') is not None and links:
                for ln in links:
                    if fb.get(ln):
                        if 'correct' in ln and 'incorrect' not in ln:
                            correct_fb = fb[ln]
                        elif 'general' in ln and 'incorrect' not in ln:
                            general_fb = fb[ln]
                        else:
                            incorrect_fb = fb[ln]
        if q['type'] in ('essay', 'file_upload', 'text_only'):
            q['answers'] = []
        elif q['type'] == 'short_answer':
            if not sa:
                # a fill-in box with no accepted answers can only be graded by hand: ship it as an essay
                q['type'] = 'essay'
                q['answers'] = []
                notes.append('%s: item %s is a short-answer box with no answer key; shipped as an essay (teacher-graded)' % (where, item.get('ident')))
            else:
                q['answers'] = [{'text': a, 'correct': True} for a in sa]
        else:
            if not labels:
                raise SystemExit('%s: item %s has no choices' % (where, item.get('ident')))
            if not correct:
                raise SystemExit('%s: item %s has no correct answer' % (where, item.get('ident')))
            q['answers'] = []
            for ident, text in labels:
                a = {'text': text, 'correct': ident in correct}
                if ans_fb.get(ident):
                    a['feedback'] = ans_fb[ident]
                q['answers'].append(a)
        if incorrect_fb:
            q['feedback_incorrect'] = incorrect_fb
        if correct_fb:
            q['feedback_correct'] = correct_fb
        if general_fb:
            q['feedback_general'] = general_fb
        questions.append(q)
    return assess.get('title') or '', meta, questions


# ---------------------------------------------------------------- the cartridge
class Cart:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = set(self.z.namelist())
        man_text = self.read('imsmanifest.xml')
        man = parse_xml(man_text.encode('utf-8'))
        m = re.search(r'<lomimscc:string[^>]*>([^<]*)<', man_text)
        self.title = html_lib.unescape(m.group(1)).strip() if m else ''
        self.resources = {}
        for r in man.iter('resource'):
            self.resources[r.get('identifier')] = dict(
                type=r.get('type', ''), href=r.get('href'),
                files=[f.get('href') for f in r.findall('file')],
                deps=[d.get('identifierref') for d in r.findall('dependency')])
        self.groups = {}
        ag = self.read('course_settings/assignment_groups.xml')
        if ag:
            for g in parse_xml(ag.encode('utf-8')).iter('assignmentGroup'):
                self.groups[g.get('identifier')] = dict(title=t(g, 'title'), weight=num(t(g, 'group_weight'), 0), position=num(t(g, 'position'), 0))
        self.modules = []
        mm = self.read('course_settings/module_meta.xml')
        if not mm:
            raise SystemExit('no course_settings/module_meta.xml: not a Canvas-flavoured cartridge')
        for mod in parse_xml(mm.encode('utf-8')).iter('module'):
            items = []
            for it in mod.findall('./items/item'):
                items.append(dict(identifier=it.get('identifier'), content_type=t(it, 'content_type'), state=t(it, 'workflow_state', 'active'),
                                  title=t(it, 'title'), ref=t(it, 'identifierref'), url=t(it, 'url'), new_tab=tb(it, 'new_tab'),
                                  indent=num(t(it, 'indent'), 0), position=num(t(it, 'position'), 0)))
            items.sort(key=lambda d: d['position'])
            self.modules.append(dict(identifier=mod.get('identifier'), title=t(mod, 'title'), state=t(mod, 'workflow_state', 'active'),
                                     sequential=tb(mod, 'require_sequential_progress'), unlock=t(mod, 'unlock_at'), items=items))

    def read(self, path):
        if path not in self.names:
            return None
        return self.z.read(path).decode('utf-8', 'replace')

    def find_meta(self, ident, kind):
        """A topicMeta whose topic_id is ident, when the manifest has no dependency."""
        for name in self.names:
            if name.endswith('.xml') and '/' not in name:
                head = self.z.read(name)[:900]
                if b'<topicMeta' in head and ('<topic_id>%s</topic_id>' % ident).encode() in head:
                    return name
        return None


# ---------------------------------------------------------------- importer
class Importer:
    def __init__(self, recipe_path):
        with io.open(recipe_path, encoding='utf-8') as fh:
            self.R = json.load(fh)
        R = self.R
        self.cart = Cart(R['cartridge'])
        self.code, self.kit = str(R['code']), R['kit']
        self.store = R.get('store') or os.path.join(os.path.dirname(REPO), 'optima-courses-2026-27')
        self.course_dir = os.path.join(self.store, 'courses', self.code)
        self.out = os.path.join(self.course_dir, self.kit + '.spec.json')
        self.pages, self.assignments, self.quizzes, self.discussions, self.files, self.modules = [], [], [], [], [], []
        self.ids = set()
        self.by_ref = {}            # cartridge resource ident -> (type, spec id)
        self.page_slugs = {}        # wiki slug -> page id
        self.pending_html = []      # (obj, key, where)
        self.pack_files = {}        # 'folder/name' -> zip path
        self.used_groups = {}       # cartridge group ident -> spec group id
        self.report = []
        self.errors = []
        self.instructure_links = 0

    # ------------------------------------------------------------ helpers
    def uid(self, prefix, base):
        base = slug(base) or 'x'
        cand, n = '%s_%s' % (prefix, base), 2
        while cand in self.ids:
            cand, n = '%s_%s-%d' % (prefix, base, n), n + 1
        self.ids.add(cand)
        return cand

    def group_id(self, cart_gid, where):
        if not cart_gid:
            return None
        if cart_gid not in self.cart.groups:
            self.errors.append('%s references unknown assignment group %s' % (where, cart_gid))
            return None
        if cart_gid not in self.used_groups:
            title = self.cart.groups[cart_gid]['title']
            title = self.R.get('rename_groups', {}).get(title, title)
            self.used_groups[cart_gid] = 'ag_' + slug(title, 30)
        return self.used_groups[cart_gid]

    def html(self, obj, key, where):
        self.pending_html.append((obj, key, where))

    def fallback_media(self, path):
        """The same demonstration clips are used across the sibling courses; a cartridge that
        lost one (a broken video in the source course) may take it from a sibling named in
        media.fallback. Exact name first, then Canvas's 'name-1.ext' duplicate suffix."""
        if not hasattr(self, '_fallbacks'):
            self._fallbacks = [Cart(p) for p in (self.R.get('media', {}) or {}).get('fallback', [])]
        stem, ext = os.path.splitext(path)
        for c in self._fallbacks:
            for cand in ('web_resources/' + path, 'web_resources/%s-1%s' % (stem, ext), 'web_resources/%s-2%s' % (stem, ext)):
                if cand in c.names:
                    self.report.append('media %r taken from %s' % (path, os.path.basename(c.z.filename)))
                    return (c, cand)
        return None

    def resolve_html(self, h, where):
        h = re.sub(r'<!--.*?-->', '', h, flags=re.S)
        h = re.sub(r'<style\b.*?</style>', '', h, flags=re.S | re.I)
        h = re.sub(r'<script\b.*?</script>', '', h, flags=re.S | re.I)
        media = self.R.get('media', {}) or {}

        def fb(m):
            raw = m.group(1).split('?')[0]
            path = urllib.parse.unquote(raw)
            zp = 'web_resources/' + path
            src = (self.cart, zp) if zp in self.cart.names else self.fallback_media(path)
            if src is None:
                self.errors.append('%s links media %r that is not in the cartridge (or any media.fallback cartridge)' % (where, path))
                return m.group(0)
            if media.get('mode') == 'pack':
                self.pack_files[path] = src
                return FIGURE_SRC + urllib.parse.quote(path)
            self.errors.append('%s embeds cartridge media %r; set media.mode to "pack" to ship it as a companion pack' % (where, path))
            return m.group(0)
        h = FILEBASE.sub(fb, h)

        def wr(m):
            s = urllib.parse.unquote(m.group(1))
            pid = self.page_slugs.get(s) or self.page_slugs.get(slug(s))
            if not pid:
                self.errors.append('%s links a page %r that is not in this kit' % (where, s))
                return m.group(0)
            return '{{page:%s}}' % pid
        h = WIKIREF.sub(wr, h)

        def orf(m):
            kind, ident = m.group(1), m.group(2)
            if kind == 'modules':
                hit = [sid for mid, sid in self.module_ids.items() if mid == ident]
                if hit:
                    return '{{module:%s}}' % hit[0]
            hit = self.by_ref.get(ident)
            want = {'assignments': 'assignment', 'quizzes': 'quiz', 'discussion_topics': 'discussion', 'pages': 'page'}.get(kind)
            if hit and hit[0] == want:
                return '{{%s:%s}}' % (want, hit[1])
            self.errors.append('%s links %s/%s which is not in this kit' % (where, kind, ident))
            return m.group(0)
        h = OBJREF.sub(orf, h)
        h = COURSEREF.sub(lambda m: '{{%s}}' % m.group(1), h)
        for pat, rep in self.R.get('replace', []):
            h = re.sub(pat, rep, h)
        self.instructure_links += len(re.findall(r'https?://[a-z0-9.-]*instructure\.com/', h))
        return h.strip()

    # ------------------------------------------------------------ objects
    def page(self, ident, item):
        if ident in self.by_ref:
            return self.by_ref[ident][1]
        res = self.cart.resources.get(ident)
        if not res or not res.get('href'):
            self.errors.append('page item %r: resource %s not in manifest' % (item['title'], ident)); return None
        doc = self.cart.read(res['href'])
        if doc is None:
            self.errors.append('page %r: file %s missing' % (item['title'], res['href'])); return None
        m = re.search(r'<title>(.*?)</title>', doc, re.S | re.I)
        title = html_lib.unescape(m.group(1)).strip() if m else item['title']
        stem = os.path.splitext(os.path.basename(res['href']))[0]
        pid = self.uid('p', stem)
        state = re.search(r'name="workflow_state"\s+content="([^"]+)"', doc)
        front = bool(re.search(r'name="front_page"\s+content="true"', doc))
        p = {'id': pid, 'title': title, 'published': (state.group(1) if state else 'active') != 'unpublished', 'html': inner_body(doc)}
        if front:
            p['front_page'] = True
        self.pages.append(p)
        self.html(p, 'html', 'page %s' % pid)
        self.page_slugs[stem] = pid
        self.by_ref[ident] = ('page', pid)
        return pid

    def assignment_fields(self, aset, where):
        a = {'points': num(t(aset, 'points_possible'), 0), 'grading_type': t(aset, 'grading_type', 'points') or 'points',
             'submission_types': t(aset, 'submission_types', 'online_text_entry,online_upload') or 'online_text_entry,online_upload',
             'published': t(aset, 'workflow_state', 'published') == 'published'}
        ext = t(aset, 'allowed_extensions')
        if ext:
            a['allowed_extensions'] = ext
        if tb(aset, 'omit_from_final_grade'):
            a['omit_from_final_grade'] = True
        g = self.group_id(t(aset, 'assignment_group_identifierref'), where)
        if g:
            a['group'] = g
        return a

    def assignment(self, ident, item):
        if ident in self.by_ref:
            return self.by_ref[ident][1]
        res = self.cart.resources.get(ident)
        if not res:
            self.errors.append('assignment item %r: resource %s not in manifest' % (item['title'], ident)); return None
        htmls = [f for f in res['files'] if f.lower().endswith('.html')]
        sets = [f for f in res['files'] if f.endswith('assignment_settings.xml')]
        if not htmls or not sets:
            self.errors.append('assignment %r: resource %s lacks html or settings' % (item['title'], ident)); return None
        doc, aset = self.cart.read(htmls[0]), parse_xml(self.cart.read(sets[0]).encode('utf-8'))
        stem = os.path.splitext(os.path.basename(htmls[0]))[0]
        aid = self.uid('a', stem if stem.lower() != 'assignment' else t(aset, 'title'))
        a = {'id': aid, 'title': t(aset, 'title') or item['title'], 'html': inner_body(doc)}
        a.update(self.assignment_fields(aset, 'assignment %s' % aid))
        self.assignments.append(a)
        self.html(a, 'html', 'assignment %s' % aid)
        self.by_ref[ident] = ('assignment', aid)
        return aid

    def quiz(self, ident, item):
        if ident in self.by_ref:
            return self.by_ref[ident][1]
        res = self.cart.resources.get(ident)
        if not res:
            self.errors.append('quiz item %r: resource %s not in manifest' % (item['title'], ident)); return None
        meta_path = '%s/assessment_meta.xml' % ident
        qti_files = [f for f in res['files'] if f != meta_path and not f.endswith('assessment_meta.xml')]
        if not qti_files:
            self.errors.append('quiz %r: no QTI file in resource %s' % (item['title'], ident)); return None
        meta = parse_xml(self.cart.read(meta_path).encode('utf-8')) if meta_path in self.cart.names else None
        qtitle, qmeta, questions = qti_questions(self.cart.read(qti_files[0]), 'quiz %r' % item['title'], self.report)
        title = t(meta, 'title') or qtitle or item['title']
        qid = self.uid('q', title)
        q = {'id': qid, 'title': title, 'quiz_type': t(meta, 'quiz_type', 'assignment') or 'assignment',
             'allowed_attempts': num(t(meta, 'allowed_attempts') or qmeta.get('cc_maxattempts') or 1, 1),
             'shuffle_answers': tb(meta, 'shuffle_answers'), 'show_correct_answers': tb(meta, 'show_correct_answers', True),
             'published': True, 'questions': questions}
        desc = t(meta, 'description')
        if desc:
            q['description'] = desc
            self.html(q, 'description', 'quiz %s' % qid)
        nested = meta.find('assignment') if meta is not None else None
        state = t(nested, 'workflow_state') if nested is not None else (t(meta, 'published') if meta is not None else '')
        if state in ('unpublished', 'false'):
            q['published'] = False
        gt = t(nested, 'grading_type') if nested is not None else ''
        if gt and gt != 'points':
            q['grading_type'] = gt
        g = self.group_id(t(meta, 'assignment_group_identifierref') or (t(nested, 'assignment_group_identifierref') if nested is not None else ''), 'quiz %s' % qid)
        if g:
            q['group'] = g
        self.quizzes.append(q)
        self.by_ref[ident] = ('quiz', qid)
        return qid

    def discussion(self, ident, item):
        if ident in self.by_ref:
            return self.by_ref[ident][1]
        res = self.cart.resources.get(ident)
        if not res or not res['files']:
            self.errors.append('discussion item %r: resource %s not in manifest' % (item['title'], ident)); return None
        topic = parse_xml(self.cart.read(res['files'][0]).encode('utf-8'))
        title = t(topic, 'title') or item['title']
        meta = None
        meta_path = None
        for dep in res['deps']:
            dr = self.cart.resources.get(dep)
            if dr and dr.get('href'):
                meta_path = dr['href']
        if not meta_path:
            meta_path = self.cart.find_meta(ident, 'topicMeta')
        if meta_path and meta_path in self.cart.names:
            meta = parse_xml(self.cart.read(meta_path).encode('utf-8'))
        did = self.uid('d', title)
        d = {'id': did, 'title': title, 'html': (topic.findtext('text') or '').strip(),
             'discussion_type': t(meta, 'discussion_type', 'threaded') or 'threaded',
             'require_initial_post': tb(meta, 'require_initial_post'),
             'published': t(meta, 'workflow_state', 'active') != 'unpublished', 'graded': False}
        nested = meta.find('assignment') if meta is not None else None
        if nested is not None:
            f = self.assignment_fields(nested, 'discussion %s' % did)
            d['graded'] = True
            d['points'] = f['points']
            if f.get('group'):
                d['group'] = f['group']
            d['published'] = d['published'] and f['published']
        self.discussions.append(d)
        self.html(d, 'html', 'discussion %s' % did)
        self.by_ref[ident] = ('discussion', did)
        return did

    def attachment(self, ident, item):
        res = self.cart.resources.get(ident)
        if not res or not res.get('href'):
            self.errors.append('file item %r: resource %s not in manifest' % (item['title'], ident)); return None
        rel = res['href'].split('web_resources/', 1)[-1]
        path = urllib.parse.unquote(rel)
        if any(f['path'] == path for f in self.files):
            return path
        dst = os.path.join(self.course_dir, 'files', path.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as fh:
            fh.write(self.cart.z.read(res['href']))
        self.files.append({'path': path, 'src': 'files/' + path})
        return path

    # ------------------------------------------------------------ run
    def run(self):
        R = self.R
        sel = R.get('modules', {}) or {}
        skip = [re.compile(p) for p in sel.get('skip_titles', [])]
        mods = [m for m in self.cart.modules if not any(rx.search(m['title']) for rx in skip)]
        if sel.get('select'):
            try:
                mods = [mods[i - 1] for i in sel['select']]
            except IndexError:
                raise SystemExit('modules.select names a module the cartridge does not have (%d modules after skip)' % len(mods))
        drop = [re.compile(p) for p in R.get('drop_items', [])]
        self.module_ids = {}
        weeks = R.get('weeks', {}) or {'mode': 'none'}
        mode = weeks.get('mode', 'none')
        per = int(weeks.get('per_module', 2))
        title_weeks = [int(m.group(1)) for mod in mods for it in mod['items'] for m in [WEEK.search(it['title'])] if m]
        base = min(title_weeks) if title_weeks else 1
        completion = bool(R.get('completion', True))
        ctype_map = {'WikiPage': 'page', 'Assignment': 'assignment', 'Quizzes::Quiz': 'quiz', 'DiscussionTopic': 'discussion',
                     'ExternalUrl': 'url', 'ContextModuleSubHeader': 'header', 'Attachment': 'file', 'ContextExternalTool': None}
        prev_week = None
        for mi, mod in enumerate(mods, 1):
            mid = self.uid('m', mod['title'][:40])
            self.module_ids[mod['identifier']] = mid
            items = []
            last_week = None
            for it in mod['items']:
                if any(rx.search(it['title']) for rx in drop):
                    self.report.append('dropped item %r (drop_items)' % it['title']); continue
                kind = ctype_map.get(it['content_type'], '?')
                if kind is None:
                    self.report.append('skipped external tool item %r' % it['title']); continue
                if kind == '?':
                    self.errors.append('module %r: unknown item type %s (%r)' % (mod['title'], it['content_type'], it['title'])); continue
                entry = {'type': kind}
                if kind == 'page':
                    ref = self.page(it['ref'], it)
                elif kind == 'assignment':
                    ref = self.assignment(it['ref'], it)
                elif kind == 'quiz':
                    ref = self.quiz(it['ref'], it)
                elif kind == 'discussion':
                    ref = self.discussion(it['ref'], it)
                elif kind == 'file':
                    ref = self.attachment(it['ref'], it)
                elif kind == 'url':
                    ref = None
                    entry['url'], entry['title'] = it['url'], it['title']
                    if it['new_tab']:
                        entry['new_tab'] = True
                else:
                    ref = None
                    entry['title'] = it['title']
                if kind not in ('url', 'header'):
                    if not ref:
                        continue
                    entry['ref'] = ref
                    obj_title = {'page': lambda: next(p['title'] for p in self.pages if p['id'] == ref),
                                 'assignment': lambda: next(a['title'] for a in self.assignments if a['id'] == ref),
                                 'quiz': lambda: next(q['title'] for q in self.quizzes if q['id'] == ref),
                                 'discussion': lambda: next(d['title'] for d in self.discussions if d['id'] == ref),
                                 'file': lambda: ref}[kind]()
                    if it['title'] and it['title'] != obj_title:
                        entry['title'] = it['title']
                if it['indent']:
                    entry['indent'] = it['indent']
                if it['state'] == 'unpublished':
                    entry['published'] = False
                if kind != 'header' and mode != 'none':
                    m = WEEK.search(it['title'])
                    if mode == 'list':
                        starts = weeks.get('starts') or []
                        w = starts[mi - 1] if mi - 1 < len(starts) else None
                    elif m:
                        w = int(m.group(1))
                    elif last_week is not None:
                        w = last_week
                    elif prev_week is not None:
                        w = prev_week + per      # the next unit starts per_module weeks after the last one
                    else:
                        w = base
                    if w is not None:
                        entry['week'] = w
                        last_week = w
                if completion and kind in ('page', 'assignment', 'quiz', 'discussion'):
                    entry['completion'] = {'page': 'must_mark_done', 'assignment': 'must_submit', 'quiz': 'must_submit', 'discussion': 'must_contribute'}[kind]
                items.append(entry)
            if last_week is not None:
                prev_week = last_week
            m_out = {'id': mid, 'title': html_lib.unescape(mod['title']), 'published': mod['state'] != 'unpublished', 'items': items}
            if mod['sequential']:
                m_out['sequential'] = True
            self.modules.append(m_out)

        # relative weeks
        if mode != 'none' and weeks.get('relative', True):
            ws = [it['week'] for m in self.modules for it in m['items'] if 'week' in it]
            if ws:
                off = min(ws) - 1
                for m in self.modules:
                    for it in m['items']:
                        if 'week' in it:
                            it['week'] -= off

        # front page
        if not any(p.get('front_page') for p in self.pages) and R.get('front_page'):
            rx = re.compile(R['front_page'])
            hit = [p for p in self.pages if rx.search(p['title'])]
            if hit:
                hit[0]['front_page'] = True
            else:
                self.report.append('front_page %r matched no page; build_kit will add a placeholder' % R['front_page'])

        # html pass (needs every id first)
        for obj, key, where in self.pending_html:
            obj[key] = self.resolve_html(obj[key], where)

        # a weighted course needs every weighted group so the weights still total 100
        if any(g['weight'] > 0 for g in self.cart.groups.values()):
            for cg, g in self.cart.groups.items():
                if g['weight'] > 0:
                    self.group_id(cg, 'course')
        order = sorted(self.used_groups, key=lambda cg: self.cart.groups[cg]['position'])
        groups = [{'id': self.used_groups[cg], 'title': self.R.get('rename_groups', {}).get(self.cart.groups[cg]['title'], self.cart.groups[cg]['title']),
                   'weight': self.cart.groups[cg]['weight']} for cg in order]
        weighted = any(g['weight'] > 0 for g in groups)
        if self.errors:
            print('\n'.join('ERROR: ' + e for e in self.errors))
            raise SystemExit('%d problem(s); nothing written' % len(self.errors))

        spec = {
            'course': {'title': R['course_title'], 'code': self.code, 'default_view': 'wiki', 'weighted': weighted, 'announcements_on_home': False},
            'assignment_groups': groups, 'rubrics': [], 'pages': self.pages, 'assignments': self.assignments,
            'quizzes': self.quizzes, 'discussions': self.discussions, 'files': self.files, 'modules': self.modules,
            'source': {'note': ('%s Imported by optima-course-kit/_build/imscc_to_spec.py from %s (cartridge title %r), modules %s of %d in '
                                'cartridge order; titles, publish state, points, groups and question content exactly as the cartridge ships them.'
                                % (R.get('note', ''), os.path.basename(R['cartridge']), self.cart.title,
                                   sel.get('select') or 'all', len(self.cart.modules))).strip()},
        }
        os.makedirs(self.course_dir, exist_ok=True)
        with io.open(self.out, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(spec, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
        self.register()
        pack = self.media_pack() if self.pack_files else None

        print('wrote', os.path.relpath(self.out, self.store))
        print('pages=%d assignments=%d quizzes=%d (questions=%d) discussions=%d (graded %d) files=%d modules=%d groups=%s%s'
              % (len(self.pages), len(self.assignments), len(self.quizzes), sum(len(q['questions']) for q in self.quizzes),
                 len(self.discussions), sum(1 for d in self.discussions if d['graded']), len(self.files), len(self.modules),
                 [(g['title'], g['weight']) for g in groups], ' WEIGHTED' if weighted else ''))
        for m in self.modules:
            print('  %-55s %3d items  published=%s' % (m['title'][:55], len(m['items']), m['published']))
        unpub = sum(1 for m in self.modules for it in m['items'] if it.get('published') is False)
        if unpub:
            print('  unpublished items: %d' % unpub)
        if self.instructure_links:
            print('  links into instructure.com left as-is: %d' % self.instructure_links)
        for r in self.report:
            print('  note:', r)
        if pack:
            print('  media pack:', pack)

    def register(self):
        c = self.R.get('course')
        if not c:
            return
        p = os.path.join(self.course_dir, 'course.json')
        if os.path.exists(p):
            with io.open(p, encoding='utf-8') as fh:
                cj = json.load(fh)
        else:
            cj = {'code': self.code, 'title': c['title'], 'grade': c['grade'], 'subject': c['subject'], 'owner': c.get('owner', 'optimaondemand'), 'kits': []}
        if not any(k['id'] == self.kit for k in cj['kits']):
            cj['kits'].append({'id': self.kit, 'label': c.get('label', self.kit)})
        else:
            for k in cj['kits']:
                if k['id'] == self.kit and c.get('label'):
                    k['label'] = c['label']
        with io.open(p, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(cj, fh, indent=1, ensure_ascii=False)
            fh.write('\n')

    def media_pack(self):
        sys.path.insert(0, os.path.join(self.store, '_build'))
        import cc  # noqa: E402
        out_dir = self.R['media'].get('pack_out') or os.path.join(os.path.dirname(self.store), 'Course Kit Media Packs')
        tmp = os.path.join(out_dir, '_tmp_' + self.kit)
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        files, manifest, total = [], [], 0
        for path, (cart, zp) in sorted(self.pack_files.items()):
            dst = os.path.join(tmp, path.replace('/', os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            data = cart.z.read(zp)
            with open(dst, 'wb') as fh:
                fh.write(data)
            files.append({'path': path, 'src': dst, 'hidden_folder': True})
            manifest.append({'path': path, 'bytes': len(data)})
            total += len(data)
        pack_spec = {'course': {'title': '%s media pack' % self.kit, 'code': self.code, 'default_view': 'modules'},
                     'assignment_groups': [], 'pages': [], 'assignments': [], 'quizzes': [], 'discussions': [], 'files': files, 'modules': []}
        out = os.path.join(out_dir, '%s-media-pack.imscc' % self.kit)
        cc.build(pack_spec, out)
        with io.open(os.path.join(out_dir, '%s-media-pack.json' % self.kit), 'w', encoding='utf-8') as fh:
            json.dump({'kit': self.kit, 'cartridge': out, 'files': manifest, 'bytes': total,
                       'note': 'Companion files-only cartridge. Import into the same Canvas course as the kit; the kit links these files by path (course files/<folder>/<file>).'}, fh, indent=1)
        shutil.rmtree(tmp)
        return '%s (%d files, %.1f MB)' % (out, len(files), total / 1048576.0)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    Importer(argv[1]).run()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
