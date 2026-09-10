# -*- coding: utf-8 -*-
"""compare_specs.py - equivalence gate: a folder-built spec against a Canvas-pulled spec.

usage: compare_specs.py <folder spec.json> <canvas spec.json> [--strict]

Modules are matched by normalised title. Within a module the item sequence is
compared title by title; graded items also compare points, quiz type and
question count. Dashes and spacing are normalised because the live course mixes
em dashes and hyphens. Exit 1 on any difference when --strict.
"""
import io
import json
import re
import sys


def norm(t):
    t = (t or '').replace('\u2014', '-').replace('\u2013', '-').replace('\u2019', "'")
    t = re.sub(r'\s*-\s*', ' - ', t)
    t = re.sub(r'\s+', ' ', t).strip().casefold()
    t = re.sub(r'[.:;,]+$', '', t)
    return t


def index(spec):
    by = {}
    for kind in ('pages', 'assignments', 'quizzes', 'discussions'):
        for o in spec.get(kind, []):
            by[o['id']] = (kind, o)
    return by


def describe(it, by):
    kind, o = by.get(it.get('ref'), (it['type'], {}))
    d = {'type': it['type'], 'title': it['title'], 'pts': o.get('points'), 'pub': it.get('published', True)}
    if it['type'] == 'quiz':
        d['qtype'] = o.get('quiz_type'); d['nq'] = len(o.get('questions', []) or [])
        if d['qtype'] in ('survey', 'practice_quiz'):
            d['pts'] = 0
    if it['type'] == 'discussion':
        d['pts'] = o.get('points')
    return d


def lcs_align(a, b):
    """Longest common subsequence on normalised titles -> list of (i, j) pairs."""
    n, m = len(a), len(b)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if a[i] == b[j] else max(L[i + 1][j], L[i][j + 1])
    i = j = 0; pairs = []
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j)); i += 1; j += 1
        elif L[i + 1][j] >= L[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def main(argv):
    strict = '--strict' in argv
    argv = [a for a in argv if a != '--strict']
    A = json.load(io.open(argv[0], encoding='utf-8')); B = json.load(io.open(argv[1], encoding='utf-8'))
    byA, byB = index(A), index(B)
    diffs = 0
    moved = 0
    print('%-14s %8s %8s' % ('count', 'folder', 'canvas'))
    for k in ('pages', 'assignments', 'quizzes', 'discussions', 'rubrics', 'files', 'modules'):
        a, b = len(A.get(k, [])), len(B.get(k, []))
        print('%-14s %8d %8d %s' % (k, a, b, '' if a == b else '<-- differs'))
    modsB = {norm(m['title']): m for m in B['modules']}
    for mA in A['modules']:
        mB = modsB.pop(norm(mA['title']), None)
        print('\n== %s' % mA['title'])
        if not mB:
            print('   !! no such module in the Canvas spec'); diffs += 1; continue
        if bool(mA.get('published', True)) != bool(mB.get('published', True)):
            print('   !! published: folder=%s canvas=%s' % (mA.get('published'), mB.get('published'))); diffs += 1
        ia = [describe(i, byA) for i in mA['items']]; ib = [describe(i, byB) for i in mB['items']]
        ta = [norm(d['title']) for d in ia]; tb = [norm(d['title']) for d in ib]
        pairs = lcs_align(ta, tb)
        onlyA = [ia[i] for i in range(len(ia)) if i not in {p[0] for p in pairs}]
        onlyB = [ib[j] for j in range(len(ib)) if j not in {p[1] for p in pairs}]
        print('   items folder=%d canvas=%d aligned=%d' % (len(ia), len(ib), len(pairs)))
        # an item present on both sides but at a different position is a MOVE, not a
        # missing item; it is reported but only counted as a difference under --strict
        tb_only = {norm(d['title']) for d in onlyB}
        ta_only = {norm(d['title']) for d in onlyA}
        for d in onlyA:
            if norm(d['title']) in tb_only:
                print('   ~ moved       : %-11s %s' % (d['type'], d['title'][:80])); moved += 1
            else:
                print('   + folder only : %-11s %s' % (d['type'], d['title'][:80])); diffs += 1
        for d in onlyB:
            if norm(d['title']) not in ta_only:
                print('   - canvas only : %-11s %s' % (d['type'], d['title'][:80])); diffs += 1
        for i, j in pairs:
            a, b = ia[i], ib[j]
            notes = []
            if a['type'] != b['type']:
                notes.append('type %s/%s' % (a['type'], b['type']))
            if a['type'] in ('assignment', 'quiz', 'discussion'):
                pa, pb = float(a.get('pts') or 0), float(b.get('pts') or 0)
                if abs(pa - pb) > 0.01:
                    notes.append('points %s/%s' % (a.get('pts'), b.get('pts')))
            if a['type'] == 'quiz' and b['type'] == 'quiz':
                if a.get('qtype') != b.get('qtype'):
                    notes.append('quiz_type %s/%s' % (a.get('qtype'), b.get('qtype')))
                if a.get('nq') != b.get('nq'):
                    notes.append('questions %s/%s' % (a.get('nq'), b.get('nq')))
            if bool(a['pub']) != bool(b['pub']):
                notes.append('published %s/%s' % (a['pub'], b['pub']))
            if notes:
                print('   ~ %-11s %-60s %s' % (a['type'], a['title'][:60], '; '.join(notes))); diffs += 1
        # order: aligned pairs are monotone by construction; report if the alignment skipped many
    for t, mB in modsB.items():
        print('\n== !! Canvas module missing from folder spec: %s (%d items)' % (mB['title'], len(mB['items']))); diffs += 1
    print('\nDIFFERENCES: %d   (moved within a module, order only: %d)' % (diffs, moved))
    return 1 if (diffs or (strict and moved)) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
