# Optima Course Kit (prototype)

One download per course section. A teacher opens the widget, types a CPALMS course
code, picks the kit for their semester, fills in a short home-page form, and downloads
a single Canvas cartridge (`.imscc`) with the whole sequenced course inside and their
own home page already set as the front page. They import it into their Canvas course
themselves. Nothing here talks to Canvas.

Live page (GitHub Pages): `https://optimaondemand.github.io/optima-course-kit/`

## What is in a kit

Everything a Canvas course is made of, in one zip, in order:

- modules and module items, with indents, publish state and sub-headers
- Canvas pages (module maps, iframe lesson pages pointing at the GitHub-hosted lessons)
- assignments with points, submission types, groups, rubrics
- classic quizzes with every question, answer, key and feedback (QTI 1.2, Canvas flavour)
- graded discussions
- assignment groups and weights, the syllabus body, bundled files
- a front page, with internal links that Canvas rewrites to the new course's URLs on import

The home page the teacher builds links each module card to the real module by
identifier (`$CANVAS_OBJECT_REFERENCE$/modules/<id>`). Canvas resolves those on import.

## Layout

| Path | What |
|---|---|
| `index.html` | The teacher-facing widget. Static. Loads JSZip from cdnjs, fetches `catalog.json`, patches one file inside the chosen cartridge in the browser, hands back the zip. |
| `catalog.json` | Generated. What the widget reads: courses, kits, status, download path, front-page path, module identifiers. |
| `catalog.seed.json` | Hand-edited. Every course a teacher might type in; kits start `pending` and flip to `ready` when a sidecar exists. |
| `cartridges/<kit>.imscc` | A built kit. |
| `cartridges/<kit>.json` | Its sidecar (written by `build_kit.py`). |
| `specs/<kit>.json` | The course spec the cartridge was built from. |
| `_build/cc.py` | Spec to cartridge. Stdlib only. Schema taken from real Canvas exports, not the IMS spec. |
| `_build/pull_canvas.py` | Read-only: live Canvas course to spec. The deployed course is the naming authority. |
| `_build/build_kit.py` | Spec to cartridge + verify + sidecar. Deletes the cartridge if verification fails. |
| `_build/verify_cartridge.py` | Structural gate: well-formed XML, every reference resolves, one front page, no unresolved link tokens. |
| `_build/make_catalog.py` | Seed + sidecars to `catalog.json`. |
| `_build/selftest.py` | Builds a tiny cartridge that uses every item type and verifies it. |

## Building a kit from a live course

```
python _build/pull_canvas.py <canvas course id> <cpalms code> specs/<kit>.json --files-dir specs/files/<code>
python _build/build_kit.py specs/<kit>.json <kit> --label "Semester 1"
python _build/make_catalog.py
```

The kit id must already exist in `catalog.seed.json`. The Canvas token is read from the
Academic Design access-tokens file; the host is `optimaoaoteam.instructure.com`.

## Building a kit from a new course (no Canvas yet)

Write the spec directly (see the docstring at the top of `_build/cc.py` for the shape
and the `{{link tokens}}`), then run `build_kit.py` and `make_catalog.py`. A build
harness that emits this spec from a course folder is the natural next step; the
generator does not care where the spec came from.

## Verifying the widget end to end

```
python -m http.server 8765
chrome --headless=new --dump-dom --virtual-time-budget=20000 "http://127.0.0.1:8765/index.html#selftest=1001310"
```

The self-test fills the example teacher, builds the patched cartridge in the page, and
writes it (base64) into the DOM so the dump can be decoded and run through
`verify_cartridge.py`. See the session notes for the exact command.

## Known limits of this prototype

- Classic quizzes only. New Quizzes need a separate QTI path.
- Cartridges carry quiz answer keys. This repo is public. Move the cartridges to a
  signed-in store (SharePoint) before students could plausibly find them.
- The front-page swap replaces the whole page body. Anything hand-edited on the
  original home page is not carried into the customized one.
- Teacher personalization beyond the home page (announcements, syllabus fields) is
  not part of the kit; do those in Canvas after import.
- Dates are not shipped. Assignments import with no due dates.
- One kit has been built and structurally verified (English 1, Semester 1, from
  Canvas course 4). It has **not yet been imported into a Canvas shell**. That
  round-trip is the next test.
