# Real OSS showcases

These recipes demonstrate three different jobs with Taskfilm and HyperFrames.
Each film opens with what the app does, records one useful task, and closes with
the result and Taskfilm's contribution. App UI is actual browser footage.

| App | Film | Useful task |
| --- | --- | --- |
| [Excalidraw](https://github.com/excalidraw/excalidraw) | Product film | Draw and connect an idea-to-launch diagram; save the editable scene |
| [drawDB](https://github.com/drawdb-io/drawdb) | Feature lesson | Create related database tables and export PostgreSQL SQL |
| [Penpot](https://github.com/penpot/penpot) | OSS walkthrough | Import original desktop and mobile layouts, inspect their native layers and retain the Penpot file |

The hosted Excalidraw and drawDB editors can change independently of a pinned
source reference. Capture receipts identify the actual URL, script bytes and
time; source references identify the inspected documentation separately.
Penpot uses a disposable self-hosted instance and sample account, with no personal
workspace or email service. Never use a private account for these captures.

Every recipe retains its capture script, original take, checked result and
editable HyperFrames composition. Rendering remains owned by HyperFrames.
The release evidence records which captures, checks and encoded films actually
completed; the presence of a recipe alone is not runtime verification.

The original 31-second Taskboard film and 24-second motion lab remain useful
installation and animation examples. They are separate from these OSS demos.

From an installed Taskfilm environment, first run `taskfilm init demo`. Excalidraw
uses its built-in browser-download fallback so headless capture can retain the
editable scene without a desktop filesystem picker:

```bash
taskfilm capture rec demo/oss-showcases/capture-excalidraw.json --out-dir takes --no-burn-captions
```

For drawDB, bind the original SQL seed to its local file before recording:

```bash
python demo/oss-showcases/prepare-capture.py demo/oss-showcases/capture-drawdb.json --out drawdb-execution.json
taskfilm capture rec drawdb-execution.json --out-dir takes --no-burn-captions
```

For Penpot, use a temporary local **2.18.2** instance following its
[self-hosting guide](https://help.penpot.app/technical-guide/getting-started/) and
[pinned compose example](https://github.com/penpot/penpot/blob/2.18.2/docker/images/docker-compose.yaml).
Enable its native `enable-demo-users` flag on frontend and backend and disable
telemetry and email for this disposable sample. The preparation helper creates
the app's temporary demo account, answers onboarding with declared synthetic
values, opens a new file and binds private browser state to an execution recipe.
It verifies the editor in a second fresh context before admitting capture. A
temporary Docker hostname uses a browser exception scoped to that exact origin
for native file staging; ordinary localhost already has that exemption.

```bash
python demo/oss-showcases/prepare-penpot.py --url http://localhost:9001 --out penpot-execution.json --auth-out auth/penpot-demo.json --proof penpot-setup-proof
taskfilm capture rec penpot-execution.json --out-dir takes --no-burn-captions
```

Keep `auth/penpot-demo.json` private and remove it after capture. The take keeps
the native `.penpot` download and screenshots, rather than copying cookies into
the result. Stop and remove the temporary instance after collecting its file.
The included `fieldnotes-layouts.svg` is original sample artwork. Penpot imports
its desktop and mobile groups as editable vectors. Its CSS references those
named groups so the native import optimizer preserves their layer names.
These are two designed
layouts; responsive application code is a separate implementation.

To author an editable film from a completed take, use its exact printed path:

```bash
python demo/oss-showcases/build-showcase.py --app excalidraw --take takes/YOUR-TAKE --out film --seconds 45
taskfilm render film --output excalidraw.mp4
```

The narrated lesson accepts `--voice narration.wav --words narration.words.json`.
Its timestamp file contains a list of `text`, `start` and `end` values in seconds.
The author aligns the lesson's native instruction beats with its spoken cues,
using bounded playback rates while retaining every source interval. Exact source
and timeline ranges remain in the evidence. It verifies the app's actual export against the retained native
download receipt before creating the composition.

The promo includes a three-second hold on its actual final diagram. The lesson
previews the retained native table screenshot while explaining the schema, then
shows the complete imported task and SQL export. The final SQL dialog is a
separate result image; it is not used as the introductory diagram.
