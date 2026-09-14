# Optima Course Kit

A teacher opens one page, types a CPALMS course code, picks the kit for their
section, fills in a short home-page form, sets dates and gradebook choices, and
downloads one Canvas cartridge (`.imscc`) with the whole sequenced course inside.
Canvas is no longer a step in distribution: cartridges are generated from the
course build folders and served from a repo.

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

## Home page themes

Step 3 opens with a theme picker. A theme carries a banner (`themes/<name>.svg`), a
palette, a Today's Spark card (`spotlights/<name>.svg`), a motif and starter wording
for the tagline and Commonplace Corner. The catalog's subject pre-picks one; the
teacher can choose any of the sixteen. Two more switches: module list as a journey
trail or the classic grid, and the spark card on or off. Optima Classic + Classic
grid + spark off is the pre-theme page.

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
across its questions in the QTI file), toggles the preview off and on, builds the
patched cartridge in the page, asserts the patched XML, and writes the zip (base64)
into the DOM so the dump can be decoded and run through `verify_cartridge.py`.

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
