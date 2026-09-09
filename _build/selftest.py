"""selftest.py - build a tiny cartridge that exercises every item type, then verify it.

Run from the repo root:  python _build/selftest.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cc  # noqa: E402

OUT = os.path.join(HERE, '..', 'cartridges', '_selftest.imscc')

spec = {
    'course': {'title': 'Course Kit Self-Test', 'code': 'SELFTEST', 'version': 'test'},
    'assignment_groups': [{'id': 'hw', 'title': 'Homework', 'weight': 40}, {'id': 'proj', 'title': 'Projects', 'weight': 60}],
    'rubrics': [{'id': 'r1', 'title': 'Essay rubric', 'criteria': [
        {'description': 'Thesis', 'long_description': 'Clear, arguable', 'points': 10,
         'ratings': [{'description': 'Strong', 'points': 10}, {'description': 'Developing', 'points': 6}, {'description': 'Missing', 'points': 0}]},
        {'description': 'Evidence', 'points': 10}]}],
    'pages': [
        {'id': 'home', 'title': 'Course Home', 'front_page': True,
         'html': '<p><a href="{{module:m1}}">Module 1</a> <a href="{{modules}}">All modules</a> <a href="{{syllabus}}">Syllabus</a> '
                 '<a href="{{page:intro}}">Intro</a> <a href="{{quiz:q1}}">Quiz</a> <a href="{{assignment:a1}}">Essay</a> '
                 '<a href="{{discussion:d1}}">Forum</a> <img src="{{file:img/dot.png}}"></p>'},
        {'id': 'intro', 'title': 'Module Map', 'html': '<p>Start here.</p>'},
        {'id': 'lesson', 'title': 'Lesson 1.01', 'html': '<p><iframe src="https://optimaondemand.github.io/hs-english-1/module-1-electra/week-1/L1.01-sophocles-and-the-greek-stage.html" style="width:100%;height:1400px;border:0"></iframe></p>'},
        {'id': 'teacher', 'title': 'Teacher notes', 'published': False, 'html': '<p>unpublished</p>'},
    ],
    'assignments': [
        {'id': 'a1', 'title': 'Module Essay', 'html': '<p>Write it. See <a href="{{page:intro}}">the map</a>.</p>', 'points': 20,
         'submission_types': 'online_upload', 'group': 'proj', 'rubric': 'r1'},
        {'id': 'a2', 'title': 'VR 1.01', 'html': '<p>Completion.</p>', 'points': 10, 'group': 'hw'},
    ],
    'quizzes': [
        {'id': 'q1', 'title': 'Week 1 Quiz', 'description': '<p>Ten points.</p>', 'quiz_type': 'assignment', 'group': 'hw',
         'shuffle_answers': True, 'allowed_attempts': 2, 'questions': [
             {'type': 'multiple_choice', 'text': '<p>Sophocles wrote in which city?</p>', 'points': 1,
              'answers': [{'text': 'Sparta', 'feedback': 'Sparta had no theatre festival of this kind.'},
                          {'text': 'Athens', 'correct': True}, {'text': 'Thebes'}, {'text': 'Rome'}],
              'feedback_correct': 'Right.', 'feedback_incorrect': 'Look again at Lesson 1.01.'},
             {'type': 'true_false', 'text': '<p>The parodos is the chorus entrance song.</p>', 'points': 1,
              'answers': [{'text': 'True', 'correct': True}, {'text': 'False'}]},
             {'type': 'multiple_answers', 'text': '<p>Which are parts of a Greek tragedy?</p>', 'points': 2,
              'answers': [{'text': 'Prologue', 'correct': True}, {'text': 'Exodos', 'correct': True}, {'text': 'Volta'}]},
             {'type': 'short_answer', 'text': '<p>Name the sacred duty of hospitality.</p>', 'points': 1,
              'answers': [{'text': 'xenia', 'correct': True}, {'text': 'Xenia', 'correct': True}]},
             {'type': 'essay', 'text': '<p>Define justice in your own words.</p>', 'points': 5},
         ]},
        {'id': 'intro', 'title': 'Module Intro', 'quiz_type': 'graded_survey', 'points': 5, 'group': 'hw', 'allowed_attempts': 1,
         'questions': [{'type': 'essay', 'text': '<p>What is justice?</p>', 'points': 0},
                       {'type': 'multiple_choice', 'text': '<p>Ready?</p>', 'points': 0, 'answers': [{'text': 'Yes'}, {'text': 'Not yet'}]}]},
        {'id': 'practice', 'title': 'Practice', 'quiz_type': 'practice_quiz', 'allowed_attempts': -1,
         'questions': [{'type': 'multiple_choice', 'text': '<p>2+2?</p>', 'points': 1, 'answers': [{'text': '4', 'correct': True}, {'text': '5'}]}]},
    ],
    'discussions': [
        {'id': 'd1', 'title': 'Is the revenge just?', 'html': '<p>Take a position.</p>', 'graded': True, 'points': 10, 'group': 'hw', 'require_initial_post': True},
        {'id': 'd2', 'title': 'Questions corner', 'html': '<p>Ask anything.</p>', 'graded': False},
    ],
    'files': [{'path': 'img/dot.png', 'bytes': bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0300050001012718e3660000000049454e44ae426082')}],
    'modules': [
        {'id': 'm1', 'title': 'Module 1: Electra', 'items': [
            {'type': 'quiz', 'ref': 'intro'},
            {'type': 'header', 'title': 'Week 1'},
            {'type': 'page', 'ref': 'intro', 'indent': 1},
            {'type': 'page', 'ref': 'lesson', 'indent': 1},
            {'type': 'url', 'title': 'Electra (Jebb translation)', 'url': 'http://classics.mit.edu/Sophocles/electra.html', 'new_tab': True, 'indent': 1},
            {'type': 'assignment', 'ref': 'a2', 'indent': 1},
            {'type': 'quiz', 'ref': 'q1', 'indent': 1},
            {'type': 'discussion', 'ref': 'd1', 'indent': 1},
            {'type': 'quiz', 'ref': 'practice', 'indent': 1},
            {'type': 'assignment', 'ref': 'a1'},
            {'type': 'file', 'ref': 'img/dot.png', 'title': 'A dot'},
        ]},
        {'id': 'm2', 'title': 'Teacher Resources', 'published': False, 'items': [
            {'type': 'page', 'ref': 'teacher'}, {'type': 'discussion', 'ref': 'd2'}]},
    ],
    'syllabus_html': '<p>Syllabus body. <a href="{{modules}}">Modules</a></p>',
}

rep = cc.build(spec, OUT)
print(json.dumps({k: v for k, v in rep.items() if k != 'module_ids'}, indent=1))
r = subprocess.run([sys.executable, os.path.join(HERE, 'verify_cartridge.py'), OUT, '--expect-items', '13'])
sys.exit(r.returncode)
