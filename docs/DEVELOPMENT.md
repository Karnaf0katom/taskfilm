# Read the code

Start with [`cli.py`](../src/taskfilm/cli.py). It maps each public command to a
small production module. [`demo.py`](../src/taskfilm/demo.py) connects those
commands for the bundled Taskboard example and stops its temporary server
when capture finishes or fails.

The production code under `_vendor/video/` is original Taskfilm code exported
from the maintained video modules. The folder name does not make it an
external dependency. It retains the production layout so fixes can return to
the same owner. The two Humanflow helpers are also project-owned; font and
reference licenses are listed in [third-party notices](../THIRD-PARTY-NOTICES.md).

| Change | Start here, under `src/taskfilm/` |
|---|---|
| Commands, install checks, render dispatch | `cli.py` |
| First-film workflow | `demo.py` |
| Resumable feature walkthrough | `pipeline.py`, `templates/preview.html` |
| Story plans and request validation | `_vendor/video/director/product_story.py`, `production_request.py` |
| Course curriculum, lesson production and packaging | `_vendor/video/director/course.py` |
| Course voice generation and imported voice delivery | `_vendor/video/edit-lane/course_narration.py`, `course_delivery.py` |
| Animation treatments and review history | `_vendor/video/director/creative_treatments.py`, `treatment_history.py` |
| Browser recording and result evidence | `_vendor/video/capture-lane/webrec.py` |
| Edit decisions and HTML composition | `_vendor/video/capture-lane/plan.py`, `hfcomp.py` |
| Recording polish and GIF export | `_vendor/video/capture-lane/polish.py`, `screen_style.py`, `gif.py` |
| Product-film visuals and sound | `_vendor/video/hyperframes-lane/product-motion/` |
| Original procedural animation | `_vendor/video/hyperframes-lane/motion-studies/` |
| Pinned repository evidence | `_vendor/video/repo-lane/repo_pack.py` |
| Preview packaging | `_vendor/video/reel-lane/demo_package.py` |
| Editable examples | `examples/` |
| Agent instructions | `skills/` |

`videokit` only resolves imports between the included production folders.
`mix/build_mix.py` supplies brand validation, and the reel grammar modules
supply the constants used by story routing. Their unrelated monorepo engines,
catalogs and execution helpers are excluded from this distribution.

There is one README and one packaged copy of each skill. `taskfilm init` and
`taskfilm skill` copy those editable sources to a destination you choose.
Recordings, account state, generated films and private cloud tools stay out
of the repository. Release and preview workflows live under `.github/`;
their small verification tools live under `release/`.

## Check a change

Follow [Contributing](../CONTRIBUTING.md) to install development dependencies.
Use the relevant tests in `tests/`; CI also tests the installed wheel and
source distribution from an unrelated directory. Real browser integration
is enabled with `TASKFILM_BROWSER_TEST=1` and needs Chromium and FFmpeg.

The initial exported tree has a hashed `SOURCE-MANIFEST.json`. Before a
release, `python release/check_source.py` verifies its complete inventory,
Python syntax and matching CLI/package versions. After editing a source
file, refresh its manifest entry's `sha256` and `bytes`; add an entry for a
new file. In the source monorepo, rerun `release/export.py` instead. Keep
`source_sha256` as the original provenance hash when editing an exported
copy. Review the resulting inventory alongside the change.

Run `python -m build` to create both distributions. Private monorepo export
and compute helpers are unnecessary for developing the standalone repository.
