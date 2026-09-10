"""cc.py - build a Canvas-flavoured IMS Common Cartridge 1.1 (.imscc) from a spec.

The file layout, element names and reference tokens were taken from real Canvas
exports of live Optima courses (Career Research 1700380, M/J Visual Art 1-3,
English 1), not from the IMS spec alone. Where the two disagree, the export wins.

Spec (a dict, usually loaded from JSON):

{
  "course": {"title": str, "code": str, "default_view": "wiki", "weighted": bool,
             "version": str},
  "assignment_groups": [{"id", "title", "weight"}],
  "rubrics": [{"id", "title", "criteria": [{"description", "long_description",
                "points", "ratings": [{"description", "points"}]}]}],
  "pages": [{"id", "title", "html", "front_page": bool, "published": bool}],
  "assignments": [{"id", "title", "html", "points", "grading_type",
                   "submission_types", "group", "rubric", "published",
                   "allowed_extensions"}],
  "quizzes": [{"id", "title", "description", "quiz_type", "points",
               "allowed_attempts", "shuffle_answers", "show_correct_answers",
               "group", "published", "questions": [QUESTION]}],
  "discussions": [{"id", "title", "html", "graded", "points", "group",
                   "published", "require_initial_post"}],
  "files": [{"path": "folder/name.ext", "src": "local file path"}],
  "modules": [{"id", "title", "published", "items": [ITEM]}],
  "syllabus_html": str
}

QUESTION = {"type": "multiple_choice|true_false|multiple_answers|short_answer|
                      essay|file_upload|text_only",
            "text": html, "points": float,
            "answers": [{"text", "correct": bool, "feedback": html}],
            "feedback_correct", "feedback_incorrect", "feedback_general"}

ITEM = {"type": "page|assignment|quiz|discussion|url|header|file",
        "ref": id-or-path, "title", "url", "new_tab", "indent", "published"}

Link tokens allowed in any HTML. Canvas rewrites them to real course URLs on
import, which is what lets a home page link to a module before the module exists:

  {{page:ID}} {{assignment:ID}} {{quiz:ID}} {{discussion:ID}} {{module:ID}}
  {{file:folder/name.ext}} {{modules}} {{syllabus}} {{grades}} {{assignments}}
  {{announcements}} {{home}}

Identifiers are deterministic (md5 of course code + kind + id), so re-importing
a rebuilt cartridge into the same Canvas course updates items in place.
"""
import hashlib
import os
import re
import urllib.parse
import zipfile
from xml.sax.saxutils import escape as _escape

CANVAS_NS = ('xmlns="http://canvas.instructure.com/xsd/cccv1p0" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 '
             'https://canvas.instructure.com/xsd/cccv1p0.xsd"')
XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'

TYPE_WEB = 'webcontent'
TYPE_LAR = 'associatedcontent/imscc_xmlv1p1/learning-application-resource'
TYPE_QTI = 'imsqti_xmlv1p2/imscc_xmlv1p1/assessment'
TYPE_DT = 'imsdt_xmlv1p1'
TYPE_WL = 'imswl_xmlv1p1'

QUESTION_TYPES = {
    'multiple_choice': 'multiple_choice_question',
    'true_false': 'true_false_question',
    'multiple_answers': 'multiple_answers_question',
    'short_answer': 'short_answer_question',
    'essay': 'essay_question',
    'file_upload': 'file_upload_question',
    'text_only': 'text_only_question',
}

TOKEN = re.compile(r'\{\{(page|assignment|quiz|discussion|module|file|modules|'
                   r'syllabus|grades|assignments|announcements|home)(?::([^}]*))?\}\}')


class SpecError(Exception):
    pass


def x(s):
    """Escape text for an XML text node or attribute."""
    return _escape('' if s is None else str(s), {'"': '&quot;'})


def b(v):
    return 'true' if v else 'false'


def pts(v):
    try:
        return '%.1f' % float(v or 0)
    except (TypeError, ValueError):
        return '0.0'


def gid(*parts):
    """Canvas-style migration id: 'g' + 32 hex chars. Deterministic on input."""
    return 'g' + hashlib.md5('\x1f'.join(str(p) for p in parts).encode('utf-8')).hexdigest()


def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()).strip('-')
    return s or 'page'


class Cartridge:
    def __init__(self, spec):
        self.spec = spec
        self.course = spec['course']
        self.code = str(self.course.get('code') or self.course['title'])
        self.entries = {}       # zip path -> bytes
        self.resources = []     # dicts: id, type, href, files, deps
        self.org = []           # organization tree (modules -> items)
        self.slugs = {}         # page id -> slug
        self.errors = []
        self.warnings = []
        self.report = {}
        self._index()

    # ------------------------------------------------------------ identifiers
    def G(self, kind, ident):
        return gid(self.code, kind, ident)

    def _index(self):
        s = self.spec
        self.pages = {p['id']: p for p in s.get('pages', [])}
        self.assignments = {a['id']: a for a in s.get('assignments', [])}
        self.quizzes = {q['id']: q for q in s.get('quizzes', [])}
        self.discussions = {d['id']: d for d in s.get('discussions', [])}
        self.modules = {m['id']: m for m in s.get('modules', [])}
        self.groups = {g['id']: g for g in s.get('assignment_groups', [])}
        self.rubrics = {r['id']: r for r in s.get('rubrics', [])}
        self.files = {f['path']: f for f in s.get('files', [])}
        for dup_name, coll in (('pages', s.get('pages', [])), ('assignments', s.get('assignments', [])),
                               ('quizzes', s.get('quizzes', [])), ('discussions', s.get('discussions', [])),
                               ('modules', s.get('modules', []))):
            ids = [i['id'] for i in coll]
            if len(ids) != len(set(ids)):
                self.errors.append('duplicate ids in %s: %s' % (dup_name, sorted({i for i in ids if ids.count(i) > 1})))
        used = set()
        for p in s.get('pages', []):
            base = slugify(p.get('slug') or p['title'])
            slug, n = base, 2
            while slug in used:
                slug = '%s-%d' % (base, n)
                n += 1
            used.add(slug)
            self.slugs[p['id']] = slug
        fronts = [p for p in s.get('pages', []) if p.get('front_page')]
        if len(fronts) > 1:
            self.errors.append('more than one front page: %s' % [p['id'] for p in fronts])
        if not self.groups and (self.assignments or self.quizzes or self.discussions):
            self.errors.append('graded items exist but no assignment_groups were given')

    # ------------------------------------------------------------------ links
    def links(self, html_text, where=''):
        def rep(m):
            kind, arg = m.group(1), (m.group(2) or '').strip()
            if kind == 'page':
                if arg not in self.pages:
                    self.errors.append('%s links to unknown page %r' % (where, arg))
                    return '#missing-page'
                return '$WIKI_REFERENCE$/pages/' + self.slugs[arg]
            if kind == 'assignment':
                if arg not in self.assignments:
                    self.errors.append('%s links to unknown assignment %r' % (where, arg))
                return '$CANVAS_OBJECT_REFERENCE$/assignments/' + self.G('assignment', arg)
            if kind == 'quiz':
                if arg not in self.quizzes:
                    self.errors.append('%s links to unknown quiz %r' % (where, arg))
                return '$CANVAS_OBJECT_REFERENCE$/quizzes/' + self.G('quiz', arg)
            if kind == 'discussion':
                if arg not in self.discussions:
                    self.errors.append('%s links to unknown discussion %r' % (where, arg))
                return '$CANVAS_OBJECT_REFERENCE$/discussion_topics/' + self.G('discussion', arg)
            if kind == 'module':
                if arg not in self.modules:
                    self.errors.append('%s links to unknown module %r' % (where, arg))
                return '$CANVAS_OBJECT_REFERENCE$/modules/' + self.G('module', arg)
            if kind == 'file':
                if arg not in self.files:
                    self.errors.append('%s links to unknown file %r' % (where, arg))
                return '$IMS-CC-FILEBASE$/' + urllib.parse.quote(arg)
            if kind == 'modules':
                return '$CANVAS_COURSE_REFERENCE$/modules'
            if kind == 'syllabus':
                return '$CANVAS_COURSE_REFERENCE$/assignments/syllabus'
            if kind == 'grades':
                return '$CANVAS_COURSE_REFERENCE$/grades'
            if kind == 'assignments':
                return '$CANVAS_COURSE_REFERENCE$/assignments'
            if kind == 'announcements':
                return '$CANVAS_COURSE_REFERENCE$/announcements'
            if kind == 'home':
                return '$CANVAS_COURSE_REFERENCE$/'
            return m.group(0)
        out = TOKEN.sub(rep, html_text or '')
        if '{{' in out and '}}' in out:
            self.errors.append('%s still contains an unresolved {{token}}' % where)
        return out

    # --------------------------------------------------------------- helpers
    def add(self, path, content):
        if path in self.entries:
            self.errors.append('zip path written twice: %s' % path)
        self.entries[path] = content.encode('utf-8') if isinstance(content, str) else content

    def res(self, ident, rtype, href=None, files=(), deps=()):
        self.resources.append(dict(id=ident, type=rtype, href=href, files=list(files), deps=list(deps)))
        return ident

    def group_ref(self, gref, where):
        if not gref:
            if len(self.groups) == 1:
                gref = next(iter(self.groups))
            else:
                self.errors.append('%s has no assignment group and the course has %d groups' % (where, len(self.groups)))
                return self.G('group', 'missing')
        if gref not in self.groups:
            self.errors.append('%s references unknown assignment group %r' % (where, gref))
        return self.G('group', gref)

    # ------------------------------------------------------------------ pages
    def build_pages(self):
        for p in self.spec.get('pages', []):
            g = self.G('page', p['id'])
            slug = self.slugs[p['id']]
            path = 'wiki_content/%s.html' % slug
            state = 'active' if p.get('published', True) else 'unpublished'
            front = '<meta name="front_page" content="true"/>\n' if p.get('front_page') else ''
            body = self.links(p.get('html', ''), 'page %s' % p['id'])
            doc = ('<html>\n<head>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
                   '<title>%s</title>\n<meta name="identifier" content="%s"/>\n'
                   '<meta name="editing_roles" content="teachers"/>\n'
                   '<meta name="workflow_state" content="%s"/>\n%s</head>\n<body>\n%s\n</body>\n</html>\n'
                   % (x(p['title']), g, state, front, body))
            self.add(path, doc)
            self.res(g, TYPE_WEB, href=path, files=[path])

    # ------------------------------------------------------------ assignments
    def assignment_xml(self, ident, a, position, extra=''):
        """Shared by stand-alone assignments and the assignment nested in a quiz / discussion."""
        rubric = ''
        if a.get('rubric'):
            if a['rubric'] not in self.rubrics:
                self.errors.append('assignment %s references unknown rubric %r' % (a.get('id'), a['rubric']))
            rubric = ('  <rubric_identifierref>%s</rubric_identifierref>\n'
                      '  <rubric_use_for_grading>%s</rubric_use_for_grading>\n'
                      '  <rubric_hide_points>false</rubric_hide_points>\n'
                      '  <rubric_hide_outcome_results>false</rubric_hide_outcome_results>\n'
                      '  <rubric_hide_score_total>false</rubric_hide_score_total>\n'
                      % (self.G('rubric', a['rubric']), b(a.get('rubric_use_for_grading', True))))
        dates = ''
        for k in ('due_at', 'lock_at', 'unlock_at'):
            if a.get(k):
                dates += '  <%s>%s</%s>\n' % (k, x(str(a[k])), k)
        if a.get('due_at') and len(str(a['due_at'])) >= 10:
            dates += '  <all_day_date>%s</all_day_date>\n' % x(str(a['due_at'])[:10])
        return (
            '  <title>%s</title>\n'
            '%s'
            '  <module_locked>false</module_locked>\n'
            '  <assignment_group_identifierref>%s</assignment_group_identifierref>\n'
            '  <workflow_state>%s</workflow_state>\n'
            '  <assignment_overrides>\n  </assignment_overrides>\n'
            '%s%s'
            '  <allowed_extensions>%s</allowed_extensions>\n'
            '  <has_group_category>false</has_group_category>\n'
            '  <points_possible>%s</points_possible>\n'
            '  <grading_type>%s</grading_type>\n'
            '  <all_day>false</all_day>\n'
            '  <submission_types>%s</submission_types>\n'
            '  <position>%d</position>\n'
            '  <turnitin_enabled>false</turnitin_enabled>\n'
            '  <vericite_enabled>false</vericite_enabled>\n'
            '  <peer_review_count>0</peer_review_count>\n'
            '  <peer_reviews>false</peer_reviews>\n'
            '  <automatic_peer_reviews>false</automatic_peer_reviews>\n'
            '  <anonymous_peer_reviews>false</anonymous_peer_reviews>\n'
            '  <grade_group_students_individually>false</grade_group_students_individually>\n'
            '  <freeze_on_copy>false</freeze_on_copy>\n'
            '  <omit_from_final_grade>%s</omit_from_final_grade>\n'
            '  <hide_in_gradebook>false</hide_in_gradebook>\n'
            '  <intra_group_peer_reviews>false</intra_group_peer_reviews>\n'
            '  <only_visible_to_overrides>false</only_visible_to_overrides>\n'
            '  <post_to_sis>false</post_to_sis>\n'
            '  <moderated_grading>false</moderated_grading>\n'
            '  <grader_count>0</grader_count>\n'
            '  <grader_comments_visible_to_graders>true</grader_comments_visible_to_graders>\n'
            '  <anonymous_grading>false</anonymous_grading>\n'
            '  <graders_anonymous_to_graders>false</graders_anonymous_to_graders>\n'
            '  <grader_names_visible_to_final_grader>true</grader_names_visible_to_final_grader>\n'
            '  <anonymous_instructor_annotations>false</anonymous_instructor_annotations>\n'
            '  <post_policy>\n    <post_manually>false</post_manually>\n  </post_policy>\n'
            % (x(a['title']), dates,
               self.group_ref(a.get('group'), 'assignment %s' % a.get('id')),
               'published' if a.get('published', True) else 'unpublished',
               extra, rubric,
               x(a.get('allowed_extensions', '')),
               pts(a.get('points')),
               a.get('grading_type', 'points'),
               a.get('submission_types', 'online_text_entry,online_upload'),
               position,
               b(a.get('omit_from_final_grade', False))))

    def build_assignments(self):
        for i, a in enumerate(self.spec.get('assignments', []), 1):
            g = self.G('assignment', a['id'])
            slug = slugify(a['title'])
            html_path = '%s/%s.html' % (g, slug)
            xml_path = '%s/assignment_settings.xml' % g
            body = self.links(a.get('html', ''), 'assignment %s' % a['id'])
            self.add(html_path,
                     '<html>\n<head>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
                     '<title>Assignment: %s</title>\n</head>\n<body>\n%s\n</body>\n</html>\n' % (x(a['title']), body))
            self.add(xml_path, XML_HEAD + '<assignment identifier="%s" %s>\n%s</assignment>\n'
                     % (g, CANVAS_NS, self.assignment_xml(g, a, i)))
            self.res(g, TYPE_LAR, href=html_path, files=[html_path, xml_path])

    # ---------------------------------------------------------------- quizzes
    def _answer_id(self, qid, n):
        return str(1000 + int(hashlib.md5(('%s:%d' % (qid, n)).encode()).hexdigest()[:6], 16) % 90000)

    def question_xml(self, quiz, q, n):
        qid = self.G('question', '%s:%d' % (quiz['id'], n))
        qtype = QUESTION_TYPES.get(q.get('type', 'multiple_choice'))
        if not qtype:
            self.errors.append('quiz %s question %d has unsupported type %r' % (quiz['id'], n, q.get('type')))
            qtype = 'essay_question'
        answers = q.get('answers', []) or []
        if qtype == 'true_false_question' and not answers:
            answers = [{'text': 'True', 'correct': True}, {'text': 'False', 'correct': False}]
        ids = [self._answer_id(qid, i) for i in range(len(answers))]
        correct = [ids[i] for i, a in enumerate(answers) if a.get('correct')]
        wrong = [ids[i] for i, a in enumerate(answers) if not a.get('correct')]
        graded_quiz = quiz.get('quiz_type', 'assignment') in ('assignment', 'practice_quiz')
        if graded_quiz and qtype in ('multiple_choice_question', 'true_false_question', 'multiple_answers_question', 'short_answer_question') and not correct:
            self.errors.append('quiz %s question %d (%s) has no correct answer' % (quiz['id'], n, qtype))
        if qtype in ('multiple_choice_question', 'true_false_question') and len(correct) > 1:
            self.errors.append('quiz %s question %d has %d correct answers; use multiple_answers' % (quiz['id'], n, len(correct)))

        meta = [('question_type', qtype), ('points_possible', pts(q.get('points', 1))),
                ('original_answer_ids', ','.join(ids)), ('assessment_question_identifierref', self.G('aq', qid))]
        out = ['      <item ident="%s" title="Question %d">' % (qid, n), '        <itemmetadata>', '          <qtimetadata>']
        for k, v in meta:
            out.append('            <qtimetadatafield>\n              <fieldlabel>%s</fieldlabel>\n              <fieldentry>%s</fieldentry>\n            </qtimetadatafield>' % (k, x(v)))
        out += ['          </qtimetadata>', '        </itemmetadata>', '        <presentation>',
                '          <material>\n            <mattext texttype="text/html">%s</mattext>\n          </material>'
                % x(self.links(q.get('text', ''), 'quiz %s q%d' % (quiz['id'], n)))]
        if qtype in ('multiple_choice_question', 'true_false_question', 'multiple_answers_question'):
            card = 'Multiple' if qtype == 'multiple_answers_question' else 'Single'
            out.append('          <response_lid ident="response1" rcardinality="%s">\n            <render_choice>' % card)
            for i, a in enumerate(answers):
                out.append('              <response_label ident="%s">\n                <material>\n                  <mattext texttype="text/html">%s</mattext>\n                </material>\n              </response_label>'
                           % (ids[i], x(self.links(a.get('text', ''), 'quiz %s q%d answer' % (quiz['id'], n)))))
            out.append('            </render_choice>\n          </response_lid>')
        elif qtype in ('short_answer_question',):
            out.append('          <response_str ident="response1" rcardinality="Single">\n            <render_fib>\n              <response_label ident="answer1" rshuffle="No"/>\n            </render_fib>\n          </response_str>')
        elif qtype in ('essay_question',):
            out.append('          <response_str ident="response1" rcardinality="Single">\n            <render_fib>\n              <response_label ident="answer1" rshuffle="No"/>\n            </render_fib>\n          </response_str>')
        out.append('        </presentation>')

        # scoring + feedback
        fb = []
        rp = ['        <resprocessing>', '          <outcomes>\n            <decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/>\n          </outcomes>']
        if q.get('feedback_general'):
            rp.append('          <respcondition continue="Yes">\n            <conditionvar>\n              <other/>\n            </conditionvar>\n            <displayfeedback feedbacktype="Response" linkrefid="general_fb"/>\n          </respcondition>')
            fb.append(('general_fb', q['feedback_general']))
        for i, a in enumerate(answers):
            if a.get('feedback'):
                rp.append('          <respcondition continue="Yes">\n            <conditionvar>\n              <varequal respident="response1">%s</varequal>\n            </conditionvar>\n            <displayfeedback feedbacktype="Response" linkrefid="%s_fb"/>\n          </respcondition>' % (ids[i], ids[i]))
                fb.append(('%s_fb' % ids[i], a['feedback']))
        correct_fb = '\n            <displayfeedback feedbacktype="Response" linkrefid="correct_fb"/>' if q.get('feedback_correct') else ''
        if qtype in ('multiple_choice_question', 'true_false_question') and correct:
            rp.append('          <respcondition continue="No">\n            <conditionvar>\n              <varequal respident="response1">%s</varequal>\n            </conditionvar>\n            <setvar action="Set" varname="SCORE">100</setvar>%s\n          </respcondition>' % (correct[0], correct_fb))
        elif qtype == 'multiple_answers_question' and correct:
            conds = ''.join('\n                <varequal respident="response1">%s</varequal>' % c for c in correct)
            conds += ''.join('\n                <not>\n                  <varequal respident="response1">%s</varequal>\n                </not>' % w for w in wrong)
            rp.append('          <respcondition continue="No">\n            <conditionvar>\n              <and>%s\n              </and>\n            </conditionvar>\n            <setvar action="Set" varname="SCORE">100</setvar>%s\n          </respcondition>' % (conds, correct_fb))
        elif qtype == 'short_answer_question':
            for i, a in enumerate(answers):
                if a.get('correct', True):
                    rp.append('          <respcondition continue="No">\n            <conditionvar>\n              <varequal respident="response1">%s</varequal>\n            </conditionvar>\n            <setvar action="Set" varname="SCORE">100</setvar>%s\n          </respcondition>' % (x(a.get('text', '')), correct_fb))
        else:
            rp.append('          <respcondition continue="No">\n            <conditionvar>\n              <other/>\n            </conditionvar>\n          </respcondition>')
        if q.get('feedback_correct'):
            fb.append(('correct_fb', q['feedback_correct']))
        if q.get('feedback_incorrect'):
            rp.append('          <respcondition continue="Yes">\n            <conditionvar>\n              <other/>\n            </conditionvar>\n            <displayfeedback feedbacktype="Response" linkrefid="general_incorrect_fb"/>\n          </respcondition>')
            fb.append(('general_incorrect_fb', q['feedback_incorrect']))
        rp.append('        </resprocessing>')
        out += rp
        for ident, text in fb:
            out.append('        <itemfeedback ident="%s">\n          <flow_mat>\n            <material>\n              <mattext texttype="text/html">%s</mattext>\n            </material>\n          </flow_mat>\n        </itemfeedback>' % (ident, x(text)))
        out.append('      </item>')
        return '\n'.join(out)

    def build_quizzes(self):
        for i, q in enumerate(self.spec.get('quizzes', []), 1):
            g = self.G('quiz', q['id'])
            meta_id = self.G('quizmeta', q['id'])
            qtype = q.get('quiz_type', 'assignment')
            if qtype not in ('assignment', 'practice_quiz', 'graded_survey', 'survey'):
                self.errors.append('quiz %s has unknown quiz_type %r' % (q['id'], qtype))
            questions = q.get('questions', []) or []
            if not questions:
                self.warnings.append('quiz %s has no questions' % q['id'])
            attempts = q.get('allowed_attempts', 1)
            items = '\n'.join(self.question_xml(q, qq, n) for n, qq in enumerate(questions, 1))
            qti_body = (
                '  <assessment ident="%s" title="%s">\n    <qtimetadata>\n      <qtimetadatafield>\n        <fieldlabel>cc_maxattempts</fieldlabel>\n        <fieldentry>%s</fieldentry>\n      </qtimetadatafield>\n    </qtimetadata>\n'
                '    <section ident="root_section">\n%s\n    </section>\n  </assessment>\n</questestinterop>\n'
                % (g, x(q['title']), 'unlimited' if int(attempts) < 0 else attempts, items))
            cc_qti = (XML_HEAD + '<questestinterop xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                      'xsi:schemaLocation="http://www.imsglobal.org/xsd/ims_qtiasiv1p2 http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_qtiasiv1p2p1_v1p0.xsd">\n' + qti_body)
            canvas_qti = (XML_HEAD + '<questestinterop xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                          'xsi:schemaLocation="http://www.imsglobal.org/xsd/ims_qtiasiv1p2 http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.xsd">\n' + qti_body)
            # Canvas reports points_possible 0 for quizzes whose questions were added
            # through the API, so an empty or zero total falls back to the question sum.
            total = q.get('points')
            if not total:
                total = sum(float(qq.get('points', 1) or 0) for qq in questions)
            state = 'published' if q.get('published', True) else 'unpublished'
            assignment_block = ''
            if qtype in ('assignment', 'graded_survey'):
                a = dict(id=q['id'], title=q['title'], group=q.get('group'), points=total,
                         grading_type='points', submission_types='online_quiz', published=q.get('published', True),
                         due_at=q.get('due_at'), lock_at=q.get('lock_at'), unlock_at=q.get('unlock_at'))
                extra = '  <quiz_identifierref>%s</quiz_identifierref>\n' % g
                assignment_block = ('  <assignment identifier="%s">\n%s  </assignment>\n'
                                    % (self.G('quizassignment', q['id']), self.assignment_xml(g, a, i, extra).replace('\n  ', '\n    ').replace('  <title>', '    <title>', 1)))
            qdates = ''.join('  <%s>%s</%s>\n' % (k, x(str(q[k])), k) for k in ('due_at', 'lock_at', 'unlock_at') if q.get(k))
            meta = (XML_HEAD + '<quiz identifier="%s" %s>\n'
                    '  <title>%s</title>\n  <description>%s</description>\n%s'
                    '  <shuffle_answers>%s</shuffle_answers>\n  <scoring_policy>keep_highest</scoring_policy>\n  <hide_results></hide_results>\n'
                    '  <quiz_type>%s</quiz_type>\n  <points_possible>%s</points_possible>\n'
                    '  <require_lockdown_browser>false</require_lockdown_browser>\n  <require_lockdown_browser_for_results>false</require_lockdown_browser_for_results>\n'
                    '  <require_lockdown_browser_monitor>false</require_lockdown_browser_monitor>\n  <lockdown_browser_monitor_data></lockdown_browser_monitor_data>\n'
                    '  <show_correct_answers>%s</show_correct_answers>\n  <anonymous_submissions>false</anonymous_submissions>\n  <could_be_locked>true</could_be_locked>\n'
                    '  <disable_timer_autosubmission>false</disable_timer_autosubmission>\n  <allowed_attempts>%s</allowed_attempts>\n  <one_question_at_a_time>false</one_question_at_a_time>\n'
                    '  <cant_go_back>false</cant_go_back>\n  <available>%s</available>\n  <one_time_results>false</one_time_results>\n'
                    '  <show_correct_answers_last_attempt>false</show_correct_answers_last_attempt>\n  <only_visible_to_overrides>false</only_visible_to_overrides>\n  <module_locked>false</module_locked>\n'
                    '%s%s'
                    '  <assignment_overrides>\n  </assignment_overrides>\n</quiz>\n'
                    % (g, CANVAS_NS, x(q['title']), x(self.links(q.get('description', ''), 'quiz %s' % q['id'])), qdates,
                       b(q.get('shuffle_answers', False)), qtype, pts(total), b(q.get('show_correct_answers', True)),
                       attempts, b(state == 'published'), assignment_block,
                       ('  <assignment_group_identifierref>%s</assignment_group_identifierref>\n' % self.group_ref(q.get('group'), 'quiz %s' % q['id']))
                       if qtype in ('assignment', 'graded_survey') else ''))
            self.add('%s/assessment_qti.xml' % g, cc_qti)
            self.add('%s/assessment_meta.xml' % g, meta)
            self.add('non_cc_assessments/%s.xml.qti' % g, canvas_qti)
            self.res(g, TYPE_QTI, files=['%s/assessment_qti.xml' % g], deps=[meta_id])
            self.res(meta_id, TYPE_LAR, href='%s/assessment_meta.xml' % g,
                     files=['%s/assessment_meta.xml' % g, 'non_cc_assessments/%s.xml.qti' % g])

    # ------------------------------------------------------------ discussions
    def build_discussions(self):
        for i, d in enumerate(self.spec.get('discussions', []), 1):
            g = self.G('discussion', d['id'])
            meta_id = self.G('discussionmeta', d['id'])
            body = self.links(d.get('html', ''), 'discussion %s' % d['id'])
            topic = (XML_HEAD + '<topic xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                     'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1  http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imsdt_v1p1.xsd">\n'
                     '  <title>%s</title>\n  <text texttype="text/html">%s</text>\n</topic>\n' % (x(d['title']), x(body)))
            state = 'active' if d.get('published', True) else 'unpublished'
            assignment_block = ''
            if d.get('graded'):
                a = dict(id=d['id'], title=d['title'], group=d.get('group'), points=d.get('points', 0),
                         grading_type='points', submission_types='discussion_topic', published=d.get('published', True),
                         rubric=d.get('rubric'), due_at=d.get('due_at'), lock_at=d.get('lock_at'), unlock_at=d.get('unlock_at'))
                assignment_block = ('  <assignment identifier="%s">\n%s  </assignment>\n'
                                    % (self.G('discussionassignment', d['id']), self.assignment_xml(g, a, i).replace('\n  ', '\n    ').replace('  <title>', '    <title>', 1)))
            meta = (XML_HEAD + '<topicMeta identifier="%s" %s>\n'
                    '  <topic_id>%s</topic_id>\n  <title>%s</title>\n  <position>%d</position>\n'
                    '  <type>%s</type>\n  <discussion_type>%s</discussion_type>\n  <has_group_category>false</has_group_category>\n'
                    '  <workflow_state>%s</workflow_state>\n  <module_locked>false</module_locked>\n'
                    '  <allow_rating>false</allow_rating>\n  <only_graders_can_rate>false</only_graders_can_rate>\n  <sort_by_rating>false</sort_by_rating>\n'
                    '  <require_initial_post>%s</require_initial_post>\n  <todo_date/>\n  <locked>false</locked>\n%s</topicMeta>\n'
                    % (meta_id, CANVAS_NS, g, x(d['title']), i, d.get('type', 'topic'), d.get('discussion_type', 'threaded'),
                       state, b(d.get('require_initial_post', False)), assignment_block))
            self.add('%s.xml' % g, topic)
            self.add('%s.xml' % meta_id, meta)
            self.res(g, TYPE_DT, files=['%s.xml' % g], deps=[meta_id])
            self.res(meta_id, TYPE_LAR, href='%s.xml' % meta_id, files=['%s.xml' % meta_id])

    # ------------------------------------------------------------------ files
    def build_files(self):
        for f in self.spec.get('files', []):
            path = 'web_resources/' + f['path'].lstrip('/')
            g = self.G('file', f['path'])
            if 'bytes' in f:
                data = f['bytes']
            else:
                src = f.get('src')
                if not src or not os.path.exists(src):
                    self.errors.append('file %s: source %r not found' % (f['path'], src))
                    continue
                with open(src, 'rb') as fh:
                    data = fh.read()
            self.add(path, data)
            self.res(g, TYPE_WEB, href=path, files=[path])

    # ---------------------------------------------------------------- modules
    def build_modules(self):
        mm = [XML_HEAD + '<modules %s>' % CANVAS_NS]
        for mpos, m in enumerate(self.spec.get('modules', []), 1):
            mg = self.G('module', m['id'])
            org_items = []
            mm.append('  <module identifier="%s">\n    <title>%s</title>\n    <workflow_state>%s</workflow_state>\n    <position>%d</position>\n'
                      '%s    <require_sequential_progress>%s</require_sequential_progress>\n    <locked>false</locked>\n    <items>'
                      % (mg, x(m['title']), 'active' if m.get('published', True) else 'unpublished', mpos,
                         ('    <unlock_at>%s</unlock_at>\n' % x(str(m['unlock_at']))) if m.get('unlock_at') else '',
                         b(m.get('sequential', False))))
            for ipos, it in enumerate(m.get('items', []), 1):
                ig = self.G('item', '%s:%d:%s' % (m['id'], ipos, it.get('ref') or it.get('title') or it.get('url')))
                t = it.get('type')
                title = it.get('title')
                ref = it.get('ref')
                ctype, identref, url, org_ref = None, None, None, None
                where = 'module %s item %d' % (m['id'], ipos)
                if t == 'page':
                    if ref not in self.pages:
                        self.errors.append('%s references unknown page %r' % (where, ref)); continue
                    ctype, identref = 'WikiPage', self.G('page', ref); title = title or self.pages[ref]['title']; org_ref = identref
                elif t == 'assignment':
                    if ref not in self.assignments:
                        self.errors.append('%s references unknown assignment %r' % (where, ref)); continue
                    ctype, identref = 'Assignment', self.G('assignment', ref); title = title or self.assignments[ref]['title']; org_ref = identref
                elif t == 'quiz':
                    if ref not in self.quizzes:
                        self.errors.append('%s references unknown quiz %r' % (where, ref)); continue
                    ctype, identref = 'Quizzes::Quiz', self.G('quiz', ref); title = title or self.quizzes[ref]['title']; org_ref = identref
                elif t == 'discussion':
                    if ref not in self.discussions:
                        self.errors.append('%s references unknown discussion %r' % (where, ref)); continue
                    ctype, identref = 'DiscussionTopic', self.G('discussion', ref); title = title or self.discussions[ref]['title']; org_ref = identref
                elif t == 'file':
                    if ref not in self.files:
                        self.errors.append('%s references unknown file %r' % (where, ref)); continue
                    ctype, identref = 'Attachment', self.G('file', ref); title = title or os.path.basename(ref); org_ref = identref
                elif t == 'url':
                    url = it.get('url')
                    if not url or not title:
                        self.errors.append('%s (url) needs both url and title' % where); continue
                    wl = self.G('weblink', '%s:%d' % (m['id'], ipos))
                    self.add('%s.xml' % wl, XML_HEAD + '<webLink xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imswl_v1p1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                             'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imswl_v1p1 http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imswl_v1p1.xsd">\n'
                             '  <title>%s</title>\n  <url href="%s"/>\n</webLink>\n' % (x(title), x(url)))
                    self.res(wl, TYPE_WL, files=['%s.xml' % wl])
                    ctype, identref, org_ref = 'ExternalUrl', ig, wl
                elif t == 'header':
                    if not title:
                        self.errors.append('%s (header) needs a title' % where); continue
                    ctype = 'ContextModuleSubHeader'
                else:
                    self.errors.append('%s has unknown type %r' % (where, t)); continue
                mm.append('      <item identifier="%s">\n        <content_type>%s</content_type>\n        <workflow_state>%s</workflow_state>\n        <title>%s</title>'
                          % (ig, ctype, 'active' if it.get('published', True) else 'unpublished', x(title)))
                if identref:
                    mm.append('        <identifierref>%s</identifierref>' % identref)
                if url:
                    mm.append('        <url>%s</url>' % x(url))
                mm.append('        <position>%d</position>\n        <new_tab>%s</new_tab>\n        <indent>%d</indent>\n        <link_settings_json>null</link_settings_json>\n      </item>'
                          % (ipos, b(it.get('new_tab', False)), int(it.get('indent', 0) or 0)))
                org_items.append((ig, org_ref, title))
            mm.append('    </items>\n  </module>')
            self.org.append((mg, m['title'], org_items))
        mm.append('</modules>\n')
        self.add('course_settings/module_meta.xml', '\n'.join(mm))

    # -------------------------------------------------------- course settings
    def build_course_settings(self):
        c = self.course
        cg = self.G('course', self.code)
        files = ['course_settings/course_settings.xml', 'course_settings/module_meta.xml',
                 'course_settings/assignment_groups.xml', 'course_settings/canvas_export.txt']
        weighted = bool(c.get('weighted')) or any(float(g.get('weight') or 0) > 0 for g in self.groups.values())
        if weighted:
            total = sum(float(g.get('weight') or 0) for g in self.groups.values())
            if abs(total - 100) > 0.01:
                self.warnings.append('assignment group weights sum to %.1f, not 100' % total)
        settings = (XML_HEAD + '<course identifier="%s" %s>\n'
                    '  <title>%s</title>\n  <course_code>%s</course_code>\n'
                    '  <is_public>false</is_public>\n  <is_public_to_auth_users>false</is_public_to_auth_users>\n'
                    '  <allow_student_wiki_edits>false</allow_student_wiki_edits>\n  <default_wiki_editing_roles>teachers</default_wiki_editing_roles>\n'
                    '  <default_view>%s</default_view>\n%s'
                    '  <license>private</license>\n  <indexed>false</indexed>\n  <hide_final_grade>false</hide_final_grade>\n'
                    '  <show_announcements_on_home_page>%s</show_announcements_on_home_page>\n  <home_page_announcement_limit>3</home_page_announcement_limit>\n'
                    '  <grading_standard_enabled>false</grading_standard_enabled>\n'
                    '  <default_post_policy>\n    <post_manually>false</post_manually>\n  </default_post_policy>\n</course>\n'
                    % (cg, CANVAS_NS, x(c['title']), x(c.get('code', '')), c.get('default_view', 'wiki'),
                       '  <group_weighting_scheme>percent</group_weighting_scheme>\n' if weighted else '',
                       b(c.get('announcements_on_home', False))))
        self.add('course_settings/course_settings.xml', settings)
        ag = [XML_HEAD + '<assignmentGroups %s>' % CANVAS_NS]
        for i, g in enumerate(self.spec.get('assignment_groups', []), 1):
            ag.append('  <assignmentGroup identifier="%s">\n    <title>%s</title>\n    <position>%d</position>\n    <group_weight>%s</group_weight>\n  </assignmentGroup>'
                      % (self.G('group', g['id']), x(g['title']), i, pts(g.get('weight', 0))))
        ag.append('</assignmentGroups>\n')
        self.add('course_settings/assignment_groups.xml', '\n'.join(ag))
        if self.spec.get('rubrics'):
            rx = [XML_HEAD + '<rubrics %s>' % CANVAS_NS]
            for r in self.spec['rubrics']:
                rg = self.G('rubric', r['id'])
                total = sum(float(cr.get('points') or 0) for cr in r.get('criteria', []))
                rx.append('  <rubric identifier="%s">\n    <read_only>false</read_only>\n    <title>%s</title>\n    <reusable>false</reusable>\n    <public>false</public>\n'
                          '    <points_possible>%s</points_possible>\n    <hide_score_total>false</hide_score_total>\n    <free_form_criterion_comments>%s</free_form_criterion_comments>\n'
                          '    <rating_order>descending</rating_order>\n    <criteria>' % (rg, x(r['title']), pts(total), b(r.get('free_form_comments', False))))
                for ci, cr in enumerate(r.get('criteria', []), 1):
                    cid = '_%s_%d' % (rg[-6:], ci)
                    rx.append('      <criterion>\n        <criterion_id>%s</criterion_id>\n        <points>%s</points>\n        <description>%s</description>\n        <long_description>%s</long_description>\n        <ratings>'
                              % (cid, pts(cr.get('points')), x(cr.get('description', '')), x(cr.get('long_description', ''))))
                    ratings = cr.get('ratings') or [{'description': 'Full Marks', 'points': cr.get('points')}, {'description': 'No Marks', 'points': 0}]
                    for ri, rt in enumerate(ratings, 1):
                        rx.append('          <rating>\n            <description>%s</description>\n            <long_description>%s</long_description>\n            <points>%s</points>\n            <criterion_id>%s</criterion_id>\n            <id>%s_%d</id>\n          </rating>'
                                  % (x(rt.get('description', '')), x(rt.get('long_description', '')), pts(rt.get('points')), cid, cid, ri))
                    rx.append('        </ratings>\n      </criterion>')
                rx.append('    </criteria>\n  </rubric>')
            rx.append('</rubrics>\n')
            self.add('course_settings/rubrics.xml', '\n'.join(rx))
            files.insert(3, 'course_settings/rubrics.xml')
        if self.spec.get('syllabus_html'):
            self.add('course_settings/syllabus.html',
                     '<html>\n<head>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n<title>Syllabus</title>\n</head>\n<body>\n%s\n</body>\n</html>\n'
                     % self.links(self.spec['syllabus_html'], 'syllabus'))
            files.insert(3, 'course_settings/syllabus.html')
        self.add('course_settings/canvas_export.txt',
                 'Built by optima-course-kit for %s (%s). Version %s.\n' % (c['title'], self.code, c.get('version', 'dev')))
        self.resources.insert(0, dict(id=cg, type=TYPE_LAR, href='course_settings/canvas_export.txt', files=files, deps=[]))

    # --------------------------------------------------------------- manifest
    def build_manifest(self):
        c = self.course
        m = [XML_HEAD,
             '<manifest identifier="%s" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource" '
             'xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imscp_v1p2_v1p0.xsd '
             'http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd '
             'http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">' % self.G('manifest', self.code),
             '  <metadata>\n    <schema>IMS Common Cartridge</schema>\n    <schemaversion>1.1.0</schemaversion>\n    <lomimscc:lom>\n      <lomimscc:general>\n        <lomimscc:title>\n          <lomimscc:string>%s</lomimscc:string>\n        </lomimscc:title>\n      </lomimscc:general>\n'
             '      <lomimscc:lifeCycle>\n        <lomimscc:contribute>\n          <lomimscc:date>\n            <lomimscc:dateTime>%s</lomimscc:dateTime>\n          </lomimscc:date>\n        </lomimscc:contribute>\n      </lomimscc:lifeCycle>\n'
             '      <lomimscc:rights>\n        <lomimscc:copyrightAndOtherRestrictions>\n          <lomimscc:value>yes</lomimscc:value>\n        </lomimscc:copyrightAndOtherRestrictions>\n        <lomimscc:description>\n          <lomimscc:string>Private (Copyrighted) - Optima Academy Online</lomimscc:string>\n        </lomimscc:description>\n      </lomimscc:rights>\n    </lomimscc:lom>\n  </metadata>'
             % (x(c['title']), c.get('date', '2026-01-01')),
             '  <organizations>\n    <organization identifier="org_1" structure="rooted-hierarchy">\n      <item identifier="LearningModules">']
        for mg, mtitle, items in self.org:
            m.append('        <item identifier="%s">\n          <title>%s</title>' % (mg, x(mtitle)))
            for ig, org_ref, title in items:
                if org_ref:
                    m.append('          <item identifier="%s" identifierref="%s">\n            <title>%s</title>\n          </item>' % (ig, org_ref, x(title)))
                else:
                    m.append('          <item identifier="%s">\n            <title>%s</title>\n          </item>' % (ig, x(title)))
            m.append('        </item>')
        m.append('      </item>\n    </organization>\n  </organizations>\n  <resources>')
        seen = set()
        for r in self.resources:
            if r['id'] in seen:
                self.errors.append('duplicate resource identifier %s' % r['id'])
            seen.add(r['id'])
            href = ' href="%s"' % x(r['href']) if r.get('href') else ''
            m.append('    <resource identifier="%s" type="%s"%s>' % (r['id'], r['type'], href))
            for f in r['files']:
                if f not in self.entries:
                    self.errors.append('resource %s lists missing file %s' % (r['id'], f))
                m.append('      <file href="%s"/>' % x(f))
            for d in r['deps']:
                m.append('      <dependency identifierref="%s"/>' % d)
            m.append('    </resource>')
        m.append('  </resources>\n</manifest>\n')
        self.add('imsmanifest.xml', '\n'.join(m))

    # ------------------------------------------------------------------ build
    def build(self, out_path):
        self.build_pages()
        self.build_assignments()
        self.build_quizzes()
        self.build_discussions()
        self.build_files()
        self.build_modules()
        self.build_course_settings()
        self.build_manifest()
        if self.errors:
            raise SpecError('%d spec error(s):\n  ' % len(self.errors) + '\n  '.join(self.errors))
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(self.entries):
                z.writestr(path, self.entries[path])
        front = [p for p in self.spec.get('pages', []) if p.get('front_page')]
        self.report = dict(
            out=os.path.abspath(out_path), bytes=os.path.getsize(out_path), entries=len(self.entries),
            pages=len(self.pages), assignments=len(self.assignments), quizzes=len(self.quizzes),
            discussions=len(self.discussions), files=len(self.files), modules=len(self.modules),
            items=sum(len(m.get('items', [])) for m in self.spec.get('modules', [])),
            front_page=('wiki_content/%s.html' % self.slugs[front[0]['id']]) if front else None,
            module_ids={m['id']: self.G('module', m['id']) for m in self.spec.get('modules', [])},
            index=self.item_index(),
            warnings=self.warnings)
        return self.report

    def item_index(self):
        """Every graded item with the zip path the Course Kit widget must patch to
        change its dates, points, group or published state."""
        gid_of_group = {g['id']: self.G('group', g['id']) for g in self.spec.get('assignment_groups', [])}
        mod_of = {}
        for m in self.spec.get('modules', []):
            for it in m.get('items', []):
                wk = it.get('week')
                if wk is None:
                    # kits pulled from Canvas carry no week; the title usually does
                    mw = re.search(r'\bWeek (\d+)\b', it.get('title') or '')
                    wk = int(mw.group(1)) if mw else None
                mod_of.setdefault((it.get('type'), it.get('ref')), (m['id'], wk))
        out = []
        for a in self.spec.get('assignments', []):
            g = self.G('assignment', a['id']); mid, wk = mod_of.get(('assignment', a['id']), (None, None))
            out.append(dict(id=a['id'], type='assignment', title=a['title'], gid=g, xml='%s/assignment_settings.xml' % g,
                            module=mid, week=a.get('week') if a.get('week') is not None else wk, kind=a.get('kind'), points=float(a.get('points') or 0),
                            points_editable=True, graded=True, group=gid_of_group.get(a.get('group')),
                            published=bool(a.get('published', True)),
                            due_at=a.get('due_at'), unlock_at=a.get('unlock_at'), lock_at=a.get('lock_at')))
        for q in self.spec.get('quizzes', []):
            g = self.G('quiz', q['id']); mid, wk = mod_of.get(('quiz', q['id']), (None, None))
            total = q.get('points') or sum(float(qq.get('points', 1) or 0) for qq in (q.get('questions') or []))
            graded = q.get('quiz_type', 'assignment') in ('assignment', 'graded_survey')
            out.append(dict(id=q['id'], type='quiz', title=q['title'], gid=g, xml='%s/assessment_meta.xml' % g,
                            module=mid, week=q.get('week') if q.get('week') is not None else wk, kind=q.get('kind'),
                            points=float(total or 0) if graded else 0.0, points_editable=False,
                            quiz_type=q.get('quiz_type', 'assignment'), graded=graded,
                            group=gid_of_group.get(q.get('group')) if graded else None,
                            published=bool(q.get('published', True)),
                            due_at=q.get('due_at'), unlock_at=q.get('unlock_at'), lock_at=q.get('lock_at')))
        for d in self.spec.get('discussions', []):
            g = self.G('discussion', d['id']); meta = self.G('discussionmeta', d['id'])
            mid, wk = mod_of.get(('discussion', d['id']), (None, None))
            out.append(dict(id=d['id'], type='discussion', title=d['title'], gid=g, xml='%s.xml' % meta,
                            module=mid, week=d.get('week') if d.get('week') is not None else wk, kind=d.get('kind'),
                            points=float(d.get('points') or 0) if d.get('graded') else 0.0,
                            points_editable=bool(d.get('graded')), graded=bool(d.get('graded')),
                            group=gid_of_group.get(d.get('group')) if d.get('graded') else None,
                            published=bool(d.get('published', True)),
                            due_at=d.get('due_at'), unlock_at=d.get('unlock_at'), lock_at=d.get('lock_at')))
        return out


def build(spec, out_path):
    return Cartridge(spec).build(out_path)


if __name__ == '__main__':
    import json
    import sys
    if len(sys.argv) != 3:
        print('usage: cc.py spec.json out.imscc')
        sys.exit(2)
    with open(sys.argv[1], encoding='utf-8') as fh:
        spec = json.load(fh)
    rep = build(spec, sys.argv[2])
    print(json.dumps(rep, indent=1))
