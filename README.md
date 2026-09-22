# Optima Course Kit

A teacher opens one page and answers one question per screen, survey style:
Welcome (customize, or just fetch a course) -> grade -> subject -> course -> preview or
configure -> whole semester or just a module (module tiles if so) -> their details ->
yes/skip for the home page, the syllabus, dates, contents and publishing, and the
gradebook -> Generate my course file (.imscc) or Download PDF, the import checklist, the
tutorial video slot, and Configure another course. Only the panels a teacher says yes to
appear. Their name, title, email, mode, term, section, meeting and Teams link are
remembered on the computer and pre-fill the next course. Canvas is no longer a step in
distribution: cartridges are generated from the course build folders and served from a
repo, and the course list rechecks the store every minute.

Live widget: https://optimaondemand.github.io/optima-course-kit/
Cartridges + catalog (current `DEFAULT_BASE`): https://optimaondemand.github.io/optima-course-cartridges/
(repo `optimaondemand/optima-course-cartridges`, three 2026-27 kits, frozen)

**Team content store for 2026-27:** `optimaondemand/optima-courses-2026-27`, one folder
per course, built for 130+ courses and ~10 builders, with its own toolchain, gate and
`CONTRIBUTING.md`. Its `catalog.json` is a light index; each kit row names a `sidecar`
the widget fetches on selection (`loadKitDetail`). Switch the widget to it by changing
`DEFAULT_BASE` in `index.html` once course content is authorized there; until then
test it with `?base=https://optimaondemand.github.io/optima-courses-2026-27/`.

## How a course becomes a kit

```
course build folder (03 Development)         recipes/<kit>.json
   Module folders, Module Maps, lesson HTML,  which folders, GitHub Pages base,
   quiz/discussion/rubric .md specs           points rules, module titles, placements
                 \                                   /
                  v                                 v
        _build/folder_to_spec.py  ->  specs/<kit>.folder.json      (a cc.py spec)
                  |
                  |  gate: _build/compare_specs.py <folder spec> <Canvas-pulled spec>
                  |        item by item against the deployed course, 0 differences
                  v
        _build/build_kit.py <spec> <kit> --label "Semester N" --root ../optima-course-cartridges
                  |  cc.py writes the cartridge; verify_cartridge.py gates it; the
                  |  sidecar <kit>.json records every graded item's XML path
                  v
        _build/make_catalog.py --root ../optima-course-cartridges  ->  catalog.json
                  v
        commit + push optima-course-cartridges; the widget reads it from Pages
```

In the 2026-27 store the same spec goes to `courses/<code>/<kit>.spec.json` and
`python _build/kit.py <kit>` there does build + verify + catalog + gate in one step;
`folder_to_spec.py` and the recipes stay here as the 7th ELA spec producer.

`folder_to_spec.py` delegates parsing to the course's own deploy harness (for 7th
ELA: `03 Development/_build/s2`: `common.classify`, `quizparse`, `mapparse`,
`sequence.order_week`, `specs`) so the kit and the Canvas deploy read the same files
the same way. A recipe may name an `extra_module` (see `recipes/ela7_s1_extra.py`)
for a semester whose conventions differ: extra classifiers, title adjustments,
synthetic records, and explicit placements read off the live course.

Sequence inside a week follows the week's Module Map, the plan the student is
shown. Where a live course was deployed from a fixed template instead, the gate
reports those items as "moved", not as differences.

## Files

| Path | What it is |
|---|---|
| `index.html` | The widget. Fetches `catalog.json` and a cartridge from the cartridge repo, patches the front page, dates, points, groups and published state inside the zip in the browser, hands back one file. Never talks to Canvas. `?base=` overrides the cartridge base URL for local testing. |
| `recipes/*.json` | One per kit: what the build folder contains and how the deployed course names things. |
| `_build/folder_to_spec.py` | Build folder + recipe -> spec. Stops on anything unclassified or ambiguous. |
| `_build/compare_specs.py` | Folder-built spec vs Canvas-pulled spec, module by module. `--strict` fails on moves too. |
| `_build/cc.py` | Spec -> Canvas-flavoured Common Cartridge 1.1. Layout copied from real exports. Deterministic ids, link tokens, dates, module unlock, item index. |
| `_build/build_kit.py` | Builds, verifies, writes the sidecar (`front_page`, `modules`, `groups`, `graded_items`, `settings`). Deletes a kit that fails verification. |
| `_build/verify_cartridge.py` | Structural gate for any `.imscc`. |
| `_build/make_catalog.py` | `catalog.seed.json` + sidecars -> `catalog.json`, in the cartridge repo. |
| `_build/pull_canvas.py` | READ-ONLY: a live Canvas course -> spec. Used only to produce the gate's reference. |
| `_build/import_test.py` | Imports a cartridge into a scratch Canvas course and prints issues and quiz question counts. |
| `specs/` | Specs: `<kit>.json` pulled from Canvas (reference), `<kit>.folder.json` built from the folder (what ships). |

## Adding a kit

1. Write `recipes/<code>-<sem>.json` (copy a 7th ELA one). Titles come from the
   deployed course, never from taste.
2. `python _build/folder_to_spec.py recipes/<kit>.json specs/<kit>.folder.json`
   until it reports no problems.
3. If the course is already live, `python _build/pull_canvas.py <canvas id> <code> specs/<kit>.json`
   and `python _build/compare_specs.py specs/<kit>.folder.json specs/<kit>.json` until 0 differences.
4. `python _build/build_kit.py specs/<kit>.folder.json <kit> --label "Semester N" --root ../optima-course-cartridges`
5. Add the course to `../optima-course-cartridges/catalog.seed.json` if new, then
   `python _build/make_catalog.py --root ../optima-course-cartridges`, commit and push that repo.
6. Optional: `python _build/import_test.py ../optima-course-cartridges/cartridges/<kit>.imscc "ZZ Kit test (delete me)"`.

## Item preview

On the dates and publishing panels (and the preview screen) every graded item's title is a link. Clicking it fetches the kit once, reads
that item's page out of the cartridge, and shows it in the preview pane: assignment
instructions, a discussion prompt, or a quiz's description and questions with their
choices (never the answers). Canvas tokens in links are disabled because they resolve
only on import; embedded lesson pages load from their live URLs. "Back to home page"
returns to the home page preview.

## Printable course (save as PDF)

On the preview screen a teacher picks **Whole course** or one module and clicks
**Open printable course**. The widget reads the module list out of the cartridge
(`course_settings/module_meta.xml` + `imsmanifest.xml`), walks every module and item in
Canvas order, and composes one HTML document in a new tab: a cover, the teacher's
customized home page, a contents list, then a module divider and every item. The tab
has a **Save as PDF** button (the browser's print dialog; choose *Save as PDF* as the
destination and turn on *Background graphics*). Nothing is uploaded anywhere.

What each item type becomes:

| Item | Printed as |
|---|---|
| Page (`wiki_content/*.html`) | The page body. Each embedded lesson `<iframe>` is fetched from its live GitHub Pages URL and placed inline inside a declarative shadow root (`<template shadowrootmode="open">`) so the lesson keeps its own CSS without leaking into the document. Lesson scripts are dropped (they only wire interactivity), every `<details>` is opened, flip cards show their back face, the read-aloud bar is hidden, the 1100px frame is widened to the page. Frames that cannot be fetched (video, forms, SharePoint) print as a labelled link. |
| Assignment | Its instructions, with points and the due date the teacher set on the dates panel. |
| Discussion | The prompt. |
| Quiz / survey | Description and every question with its choices, never the answers (same reader as the item preview). |
| File | Its file name. |

Unpublished modules and items (from the kit, or unpublished by the teacher on the publishing panel) are
left out, so the document is what a student will actually meet. A whole semester of 7th
ELA S2 is 4 published modules, 208 items, 101 lesson pages, about 1,400 Letter pages;
composing it takes a few seconds plus the lesson fetches, and Chrome's print dialog needs
a moment to paginate it. One module is a few hundred pages.

The gate for this is a PDF, not the HTML: `#printtest=CODE:KIT-ID[:all|:<module gid>]`
composes the document alone and writes it into `<pre id="print-html">`; the scratch
`gate.py` (in the session that built this) dumps the DOM, saves the document, prints it
with headless Chrome, and asserts on the PDF text: cover, contents, every item title,
module dividers = modules composed, quiz questions present, no answer XML, and any
phrase you pass as a needle. The regular `#selftest` also composes the first content
module and asserts items = sections, lessons = shadow roots, no scripts, no answers.

Limits: the printable copy is a document, so interactive widgets show their options
without feedback; pop-up blockers that refuse the new tab get the same document as a
downloaded `.html` file instead (open it and press Ctrl+P); browsers older than 2024
without declarative shadow DOM will print the lessons with their styles bleeding
together.

## The journey (survey-style screens)

| Screen | What it does |
|---|---|
| Welcome | "Welcome to the Course Optimizer!" Two tiles: **Customize my course** (the full journey) or **Just fetch a course** (grade -> subject -> course -> part -> download, no configuration). Greets a returning teacher by name. |
| Grade, subject, course | Tiles built from `catalog.json`: K-12 with counts (empty grades greyed), subjects with counts for that grade, then course tiles (Honors/Standard pills, code, "n of m kits ready"; no ready kit = greyed "Coming"). A folded **Search the full course list** keeps the old finder (search box, grade chips, subject filter, list). |
| Preview or configure | **Preview the course** shows the home page in the pane, every module's items (click a graded item to read it) and the printable course; **Configure it for Canvas** continues. **Configure for Canvas** goes straight on. |
| Whole semester or a module | One tile per kit (pending kits greyed), the Live/On-Demand switch when a course has kits per mode, and **Just a module** -> module tiles from every ready kit (multi-select within one kit) -> Continue. |
| Tell us about you | Name, title, email, mode, term, section, meeting, Teams link. Saved to `localStorage` `optima-course-kit-teacher` and applied to every new kit's home page and syllabus. |
| Yes/skip gates | Home page (theme, blurb, house, tagline, module cards), syllabus, dates, contents and publishing, gradebook. Skip = the panel never appears; the standard syllabus still ships unless it is switched off. Dates and publishing share one panel; each gate shows only its own controls (`#dates-panel.mode-dates` / `.mode-publish`). Every panel screen also has **Skip this step** in a line under its heading and beside Continue: the answer flips to skip and that panel goes back to the kit's defaults (`resetPanel`); if the teacher changed something there, the first click arms ("Discard my changes here and skip") and a second click within 6 s does it. The summary chips on Generate read the actual state (`panelChanged`), so "customized" means something changed. Continue/Skip stick to the bottom of the viewport while a long panel scrolls. |
| Generate | Summary chips (course, scope, what was customized), **Generate my course file (.imscc)**, **Download PDF** (the printable course), copy home page HTML, original kit; the import checklist; the tutorial video (`TUTORIAL_VIDEO_URL`, a "coming soon" card while empty); **Configure another course** (keeps the teacher's details, clears the course). |

Back and Start over sit above every screen with a dot trail ("Step n of N", computed from
the answers so far). The screen, path and answers persist per browser (`uiPref().journey`);
a reload keeps the course and returns to the "whole semester or a module" screen because
the kit itself is not persisted. `#screen=NAME[:CODE[:KIT-ID]]` opens one screen directly
(review links, screenshots).

**Module-only kits.** Choosing modules sets `home.onlyModules` (module ids, per kit). On
build every other module leaves `module_meta.xml` (whole `<module>` block), the manifest
organization (balanced `<item>` cut, `cutXmlItem`) and, when nothing kept still points at
it, the cartridge: pages, assignments, quizzes and discussions of dropped modules lose
their resources and files; course files (`Attachment`) always stay because a kept page may
link to them. The home page shows only the kept module cards, the dates/gradebook/print
panels list only kept modules, and the filename carries the module (`...-module-1-electra-...`).
A module-only file is an **add-on** to a course the teacher already has: the journey skips the details, home page and syllabus steps (`sequence()` when `J.scope === 'modules'`), and the build (`moduleAddon()`) leaves the kit's front page out of the cartridge (its resource and file go with `removeFromZip`), writes no `syllabus.html`, and strips `<default_view>` from `course_settings.xml`, so importing it into a live course adds the module and changes nothing else. Canvas imports never delete existing content; items with the same identifier are updated in place. Whole English 1 S1 = 301 entries; Module 1 alone = 79, `verify_cartridge.py` PASS on both. Not yet import-tested into a course with a customized home page.

## Home page themes

The home page panel opens with a theme picker. A theme carries a banner (`themes/<name>.svg`), a
palette, a motif and a starter tagline. The catalog's subject pre-picks one; the
teacher can choose any of the sixteen. One more switch: module list as a journey
trail or the classic grid. Optima Classic + Classic grid is the pre-theme page.

Retired 2026-09-17 on the curriculum lead's ruling: the first-announcement fields,
the Commonplace Corner (quote, author, prompt) and the Today's Spark card. The
`spotlights/*.svg` files stay hosted because home pages imported before that date
still point at them.

## The syllabus panel (gate: "Do you want to review your syllabus?")

The kit fills the course's Canvas **Syllabus** page. The step is the syllabus builder
from `teacher-homepages/syllabus.html`, lifted into `index.html` by markers (constants,
document model, Canvas emitter, list forms) and kept in its own scope (`Syl`), so a
syllabus built here matches one built there and the download reopens in the standalone
builder (same `OAO-BUILDER` payload). The Word output stays in the standalone builder.

What the kit fills in: title, code and grade band from the catalog course; badges from
the kit label and grade; the description from `syllabus-courses.json` (fetched from
teacher-homepages, blank when the catalogue has none); the grading cards from the
gradebook groups and weights (the gradebook panel), following them until the teacher edits the cards;
teacher name, email, class meeting and Live/On-Demand mode from the details screen on every render
and build, never typed twice. Every stock section can be edited or switched off; the
teacher's own sections (paragraphs, bullets, small table, highlighted note) slot in
wherever she chooses. State lives in `home.syllabus`, saved per kit with the rest.

On build the widget writes `course_settings/syllabus.html` and lists it in the
course_settings resource of `imsmanifest.xml` (the tickbox at the top of the step turns
this off). The home page's Syllabus tile already points at Canvas's own Syllabus tab, so
it needs no change. **Mid-year changes:** come back, edit, **Copy syllabus HTML**, and
paste into Syllabus, Edit, HTML editor in the live course; the tile keeps working.
The self-test asserts the file is in the zip and the manifest, is ASCII only, and carries
the course title, the step-3 teacher and the gradebook's weights.

## Dates, publishing and contents (two gates, one panel)

Every module in the kit gets a block: a Publish all / Unpublish all pair (the module
and everything inside it, both ways), the batch date row, the graded-item table with
a Published column, and a **Module contents** list read from the cartridge's own
`module_meta.xml` (the sidecar knows graded items only). Each entry has a Remove
button (Restore once removed). Removal lives only in the teacher's browser state and
the cartridge she downloads: a removed assignment, quiz or discussion loses its module
entry, organization entry, manifest resource (plus the resources it depends on) and
files, so it never reaches the gradebook; a removed page leaves the module but keeps
its resource and file, so it stays in the course's Pages. Nothing in the store changes.
The gradebook panel, the printable course and the self-test all skip removed items.

The SVGs are hosted here on Pages and reach Canvas as plain `<img>` tags (Canvas
strips `data:` images). Their CSS animation runs inside `<img>` and every file
honours `prefers-reduced-motion`. The themed page is still pure ASCII with inline
styles only. Source of the design: the theme-and-motion review artifact (2026-09-12).

## Course tiles tab

The second tab makes Canvas dashboard tiles (1920 x 1080 PNG). Set how many tiles, then
click tiles on the right to select them (Ctrl-click adds to the selection) and fill in
course title, teacher, the Live / On-Demand pill (or none), period, days, time and the
tile style on the left. What you type goes on every selected tile, so select all five
sections for the shared details and one at a time for the period. A field that differs
across the selection shows "(varies)". A new tile starts as a copy of the last one. The
form pane and the preview pane scroll independently; each tile downloads alone or all
together as a zip.

Backgrounds live in `tiles/` (one per band and subject, `tiles/manifest.json` names
the source tile each came from). They are the 2026-27 tile set with the course title
and teacher name erased; `_build/tile_backgrounds.py` regenerates them from the
Upper/Middle zips. The pill is erased too (`_build/tile_backgrounds.py` inpaints it by extending the
wave boundary). The text is drawn in the browser in Poppins, larger than the originals
because dashboard cards shrink the image, and the pill is drawn only when asked for.

## Verifying the widget end to end

Serve the parent folder of both repos, then load the widget with a local base:

```
cd "..\GitHub"; python -m http.server 8793 --bind 127.0.0.1
chrome --headless=new --dump-dom --virtual-time-budget=40000 "http://127.0.0.1:8793/optima-course-kit/index.html?base=/optima-course-cartridges/#selftest=1001040:1001040-s2"
```

The self-test fills the example teacher, applies sample dates, weights, points and
a publish change, batch-dates one whole module, sets a graded quiz total (split evenly
across its questions in the QTI file), removes one graded item and one page from the
first content module, unpublishes then republishes a second module, toggles the
preview off and on, builds the patched cartridge in the page, asserts the patched XML
(including the removal: entries, resource and files gone for the graded item; page
resource kept), and writes the zip (base64) into the DOM so the dump can be decoded
and run through `verify_cartridge.py`. From Git Bash, pass the `?base=/...` URL as one
quoted string (or set `MSYS_NO_PATHCONV=1`), or the shell rewrites the leading slash
into a Windows path and the widget fetches nothing.

## Verifying a kit in Canvas itself

```
python _build/import_test.py <cartridge> "ZZ Kit test <kit> (delete me)" [canvas_cartridge_importer|common_cartridge_importer] [--new-quizzes]
```

Verified 2026-09-10 on both importers: 0 issues, every survey intact. With
`--new-quizzes` (Canvas's "Import existing quizzes as New Quizzes" checkbox) the
graded quizzes convert but every ungraded survey becomes an empty external-tool
assignment. The widget's checklist tells teachers to leave that box unchecked.

## Known limits

- Classic quizzes only. New Quizzes need a separate QTI path.
- Ungraded surveys (module Intro and Outro) do not survive the New Quizzes import
  option. Teachers must import as classic quizzes.
- Cartridges carry quiz answer keys and the cartridge repo is public, by decision
  for the 2026-27 year. Move them to a signed-in store before that changes.
- The front-page swap replaces the whole page body.
- Quiz points are the sum of their questions and are not editable in the widget.
