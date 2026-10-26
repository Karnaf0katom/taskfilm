# Taskfilm

**Make short videos that teach people how to use your software.**

[![CI](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml/badge.svg)](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Build a feature, then show people how to use it. Taskfilm records a real browser
workflow and turns it into a short, editable video with HyperFrames. Use it for
feature handoffs, onboarding, release notes and tool walkthroughs. Run the local
CLI yourself or give its included skill to your coding agent.

For a complete course, the [course workflow](docs/COURSES.md) coordinates ordered
lessons, scripts, narration, editable films, practice tasks and a learner ZIP.
Instructors can add personal voiceovers and refine individual cuts; batch builds
reuse unchanged lessons and keep prior versions. Included in **0.1.0a6**.

**Watch Taskfilm in action (43 seconds)**

![Animated demo: the agent builds a feature, creates an explainer video, and delivers it in chat](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a2/taskfilm-ccc-demo-v4.gif)

The full demo plays here automatically (silent). See the agent build an update,
make a video explaining what changed, and deliver it in the same chat.
[Download the MP4 with narration (4.7 MB)](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a2/taskfilm-ccc-demo-v4.mp4).

[Watch the examples](https://karnaf0katom.github.io/taskfilm/) ·
[Download the release](https://github.com/Karnaf0katom/taskfilm/releases) ·
[Workflow guide](docs/WORKFLOWS.md)

Start with a real task: where to find the feature, the actions to take, and the
visible result. Captures retain timed actions and result screenshots so the
explanation stays tied to the app it shows.

Compare the [preview gallery and production options](docs/PREVIEWS.md): recorded
feature lessons, directed product films, After Effects-style HTML/SVG motion,
OSS walkthroughs and portrait reels. The downloadable projects keep the real
take, native result and editable composition together.

## Revit lessons in Hebrew: Windows starter

[Download the Windows starter ZIP](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a4/Taskfilm-Revit-Starter.zip) ·
[Setup guide and Hebrew instructions](docs/REVIT-COURSE.md)

Prepare short classroom demonstrations with an installer, Hebrew menu, lesson
and feedback templates, OBS recording, recorded-action replay and optional
Hebrew narration. Extract the ZIP and start with `00-SETUP.cmd`.
A voice key is supplied privately. The Windows/Revit flow still needs acceptance
on the recipient's PC; autonomous execution of new Revit tasks is unverified.

## Build a feature. Explain it.

Give your agent one checked task and ask for its walkthrough:

> Make the watchlist easier to scan. Use `$taskfilm-feature-explainer` to show
> the upgrade once it works and its checks pass.

[See the animated workflow demo above](#taskfilm) ·
[Watch the resulting feature walkthrough](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a2/taskfilm-watchlist-upgrade-20261015.mp4)

The edited demo shows a UI upgrade request in CCC with Codex, a time skip,
and the actual feature video playing inside the same conversation.
Prompt entry is re-recorded; the feature change and inline playback are real.
The Trading Terminal uses labeled sample quotes.

Your agent uses the same capture, composition and render commands as you. A
recorded lesson can accompany the feature handoff, release notes or an onboarding
guide. The [build-and-explain guide](docs/BUILD-AND-EXPLAIN.md) covers the focused
workflow and which release includes it. Installing a skill makes the workflow
available to your agent; it does not install a background watcher.

## Deliver a checked feature in one command

```bash
taskfilm run demo/capture.json --out lesson --json
```

Use your own capture script against the running app. The command retains the
verified take, captions, editable composition and playable preview; unchanged
stages can resume with `--resume`. See the [one-run guide](docs/AGENT-RUN.md)
for source hashes, reusable takes and the feature-explainer skill.

## What you get

- **Real browser recordings** with timed actions, clicks, DOM assertions and hashed result screenshots.
- **Three story modes:** teach a feature, promote a product, or explain an OSS tool with pinned source attribution.
- **Editable motion:** camera moves, kinetic type, perspective, click effects, recap shots and original synthesized sound.
- **Your source files:** the original take, edit decisions, HTML/SVG composition and rendered MP4 stay local.
- **An agent skill** that uses the same CLI commands as you.

The sample needs no account, API key, GPU or model download. Rendering downloads
the pinned HyperFrames runtime and GSAP; an offline render is not promised.

## Install

Requires **Python 3.10+**. Capture needs **FFmpeg/FFprobe** and **Chromium**;
rendering needs **Node.js 22+** and **npm**. Linux is the checked platform for
this first alpha; macOS and Windows have not been verified.

```bash
git clone https://github.com/Karnaf0katom/taskfilm.git
cd taskfilm
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser,motion]'
python -m playwright install chromium
taskfilm doctor
taskfilm capture check
```

On Windows, activate with `.venv\Scripts\activate`. Install FFmpeg separately
with your system package manager; on Ubuntu use `sudo apt-get install ffmpeg`.
If Chromium needs Linux system libraries, use
`python -m playwright install --with-deps chromium`.

Upgrade using the wheel from [Taskfilm 0.1.0a6](https://github.com/Karnaf0katom/taskfilm/releases/tag/v0.1.0a6):

```bash
python -m pip install --upgrade "./taskfilm-0.1.0a6-py3-none-any.whl[browser,motion]"
taskfilm --version
```

Distribution is through GitHub Releases; PyPI publication is not configured.

## Make your first film

The included Taskboard is an original local app. This recipe adds a task,
marks it complete and shows the result. Tasks use browser local storage.

```bash
taskfilm demo my-first-film --render
```

This starts a temporary local server on an available port, records the real
task, checks its three result screenshots, and creates an editable lesson plus
`my-first-film/lesson.mp4`. The server stops after capture. You need no account,
API key or second terminal. The destination must be a new directory.

The folder retains `sample/`, the exact `take`, `story-plan/`, `composition/`,
stage logs and `DEMO-RESULT.json`. Edit `composition/index.html` to customize
the lesson. The original capture stays available for later edits.

To prepare the editable project first and render it later:

```bash
taskfilm demo my-first-film
taskfilm render my-first-film/composition --output my-first-film/lesson.mp4
```

For a faster trial encode, use `taskfilm demo my-first-film --render --quality draft`.
If a stage fails, read the named log under `my-first-film/logs/`; its sample and
capture evidence remain available. Retry in a new directory. Review the finished
movie before sharing it. [Manual commands](docs/WORKFLOWS.md#try-one-real-task)
show how to adapt the workflow to your own app.

To try a scored 31-second product promo with kinetic titles, camera moves and
animated recap cards in both landscape and portrait:

```bash
taskfilm demo my-product-film --mode promo --format both --render --quality draft
```

Install the `motion` extra first. One real 4K take supplies both editable cuts,
four verified result screenshots and an original synthesized score. Omit
`--render` to prepare the projects first. The report names each composition,
edit-decision record and rendered movie. Review the finished cuts before sharing.
The [motion recipes](docs/WORKFLOWS.md) explain customization and the separate
24-second animation study.

For a narrated app showcase, use the [Excalidraw motion-promo recipe](docs/WORKFLOWS.md#make-a-narrated-excalidraw-motion-promo).
It combines a real workflow with masked type, a perspective reveal, camera
choreography and animation of the saved diagram. Bring narration and a licensed
score, or prepare them with the [media commands](docs/ADS.md).

## Make original animation

Choose a treatment that changes the storytelling and motion: physical typography,
an orbital perspective journey, or a procedural line sculpture. Both landscape
and portrait layouts retain editable sources and an original synthesized score.

```bash
taskfilm treatments --brief "A bold launch headline" --seed 41
taskfilm animate my-animation --treatment type-sculpture --headline "Make it move."
taskfilm render my-animation --output my-animation.mp4
taskfilm animate variety-reel --showreel --format portrait
taskfilm render variety-reel --output variety-reel.mp4
```

The `motion` extra supplies audio; `--silent` authors without it. Use `--history`
to avoid recently reviewed structures while keeping your brand palette.
Read the [animation guide](docs/ANIMATION.md) for treatments, seeking and review.
Craft research credits [Tejas Makwana's Motionmaxxing](https://github.com/Tejashmakwana/motionmaxxing);
the included animation artwork and recipes are original Taskfilm work.

Reuse your colours and copy with `--brand-file demo/brand.json`; `taskfilm init demo`
includes an editable example. Explicit flags override the file. See the
[brand-file guide](docs/BRAND-KIT.md).

After watching the finished movie, record that review for future treatment selection:

```bash
taskfilm record-review my-animation --movie my-animation.mp4 --history history.json \
  --reviewer "Your name" --confirm-reviewed
taskfilm animate next-animation --history history.json --brand-file demo/brand.json
```

The command hashes the supplied movie and retains your review declaration. It does
not watch the film or certify its quality. See [review history](docs/REVIEW-HISTORY.md).

## Polish a recording you already have

Import your screen recording with a reusable frame style, source-time cuts and
speed edits, zooms, text labels and optional cursor/click effects. The original
clip and audio remain available with the editable composition and JSON edits.

```bash
taskfilm polish recording.mp4 my-screencast --preset paper
taskfilm render my-screencast --output screencast.mp4
taskfilm gif screencast.mp4 --output preview.gif --width 960 --fps 15
```

Read the [screencast guide](docs/SCREENCAST.md) for precise edits, automatic
focus from supplied clicks, portrait framing and saved styles. The
[OpenScreen comparison](docs/OPENSCREEN-COMPARISON.md) records what this original
implementation adds and the desktop features outside its current scope.

## Plan the story

For ads with varied compositions, authentic brand assets, narration, real music,
captions, optional lip-synced presenters, and scheduled social publishing, use the
new [ad workflow](docs/ADS.md). `taskfilm ad` selects from eight extensible layout
families and learns from local history/ratings. `taskfilm media` handles audio
and final delivery; `taskfilm publish` supplies a durable scheduled posting queue.
The original lesson and product-motion paths remain available.

For a visual stage-by-stage workspace with complete downloadable file versions,
scene and narration editing, restore and selective resume, use
[Taskfilm Studio](docs/STUDIO.md): import a workspace, register it in a Projects library,
and serve with `taskfilm studio serve LIBRARY --library`. Browse thumbnails, open
individual editors, create drafts and duplicate complete projects.

```bash
taskfilm story --request demo/request.json --story demo/feature.json --out feature-plan
taskfilm story --request demo/request.json --story demo/promo.json --out promo-plan
```

Story planning exports direction and capture requirements. Record the task,
apply the direction to your composition and review the finished film. A plan
does not execute the workflow or prove the result.

| Goal | Mode | Recipe |
| --- | --- | --- |
| Teach one useful task | `feature_demo` | Natural-speed actions and a readable result |
| Promote a product | `saas_launch` | Problem, real workflow, payoff and supplied CTA |
| Explain an OSS tool | `github_review` | Pinned source, real task, fit and limitation |

The [OSS recipes](src/taskfilm/examples/oss-showcases/README.md) cover
Excalidraw diagrams, drawDB schemas and a prepared Penpot design handoff.
The 45-second Excalidraw film and 72-second drawDB lesson retain checked native
exports. **Penpot's complete capture, native export and film remain unverified.**
The showcase films were recorded before the public rename and retain the earlier wordmark.

## Adaptive workflows with OpenGCUA

Use the optional [OpenGCUA capture mode](docs/OPENGCUA.md) when a browser task
needs branches, loops, accessibility targets or visual interaction. A trusted
Python program uses the real SDK while Taskfilm records its tab, narration beats
and checked result screenshots into the existing editable take format.

```bash
taskfilm capture gcua demo/opengcua-taskboard.py \
  --url http://127.0.0.1:8765/ --out takes/adaptive-taskboard
taskfilm edit takes/adaptive-taskboard --no-retime
```

This preview integration needs Python 3.11+, the separately installed
OpenGCUA 0.1.2 wheel and its browser setup. It uses sampled screenshots;
`capture rec` remains the smooth recording route for known scripts.
The [guide](docs/OPENGCUA.md) includes setup, the local example and evidence limits.
No model, account or API key is needed for the example.

## Use with an agent

For the build → checked feature → walkthrough flow, start with
[Build a feature, then explain it](docs/BUILD-AND-EXPLAIN.md). It includes the
setup commands, a prompt for your own app, review steps and in-chat controls.

```bash
taskfilm skill ~/.codex/skills/taskfilm-video
```

Choose the skill folder used by your agent. Existing destinations are never
overwritten. The [included skill](src/taskfilm/skills/taskfilm-video/SKILL.md) explains the
capture, composition, motion and evidence workflow; it requires no private checkout.

For a feature upgrade that should end with a short how-it-works lesson, install
the focused workflow too:

```bash
taskfilm skill ~/.codex/skills/taskfilm-feature-explainer --name taskfilm-feature-explainer
```

Ask your agent: “Use `$taskfilm-feature-explainer` while building this feature.
When a useful milestone works and its checks pass, film it in the background and
show progress and a preview in this chat so I can stop, continue or request changes.”
The [feature skill](src/taskfilm/skills/taskfilm-feature-explainer/SKILL.md) detects readiness,
keeps demos tied to the version shown, and delivers an editable project, a reviewed
movie and short usage steps. Background filming uses one temporary helper when
your agent supports it; otherwise the owning agent performs the stages itself.
Say “stop filming” to stop the demo, “continue filming” to resume valid work, or
describe a change to the feature or video. The same chat keeps control.

It uses the same capture and render owners. Installation makes the skill
discoverable; it does not start an always-on watcher or service. Narration uses
supplied audio or a separately authorized provider; captioned silence is supported.

## Commands

| Command | Purpose |
| --- | --- |
| `doctor`, `init`, `skill` | Check tools, copy samples and install the skill |
| `demo DIRECTORY [--mode promo] [--format both] [--render]` | Record the sample and prepare a lesson or directed product films |
| `story` | Plan a feature lesson, promo or OSS walkthrough |
| `capture` | Validate, discover and record a browser workflow |
| `edit` | Prepare edit decisions from a take |
| `compose`, `reel` | Create landscape or portrait HTML compositions |
| `polish` | Import a recording with reusable styles, precise edits and optional cursor overlays |
| `gif` | Convert a finished movie or excerpt to a palette-optimized GIF |
| `motion` | Author the directed product-film kit |
| `treatments` | Choose a reproducible motion treatment with recent-history avoidance |
| `animate` | Author original motion graphics or a three-family showreel |
| `record-review` | Record your explicit film-review declaration for subsequent treatment selection |
| `render` | Check and render with pinned HyperFrames 0.8.134 |
| `repo-pack` | Retain pinned repository source and attribution |
| `package` | Package evidence or checked films and downloads |

Run `taskfilm COMMAND --help` for each input contract.

## Privacy and scope

Capture uses a fresh browser context by default. Keystroke event logs redact
characters, but the screen still records visible text. Review footage before
sharing. Keep authentication state, cookies and browser profiles outside your
take bundles and repository. Run capture scripts and setup JavaScript you trust.

This alpha provides a local CLI and editable compositions. Narration and presenter
generation are optional integrations through video-claw; social publishing uses
an explicitly configured worker and platform accounts. Hosted orchestration,
a timeline editor, repository sandbox execution and
Adobe After Effects project import are outside its scope. Source assertions,
capture checks and final visual review remain separate evidence.

## Contribute

```bash
python -m pip install '.[browser,motion,dev]'
python -m pytest -q
# Optional real-browser task; requires FFmpeg and installed Chromium.
TASKFILM_BROWSER_TEST=1 python -m pytest -q
```

Start with the [code map](docs/DEVELOPMENT.md) to find the module to change.
See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
[RELEASE.md](RELEASE.md). CI tests installed wheels and source distributions
outside the checkout, records the original browser task, and checks audio
through a complete HyperFrames render.

## License

Original code is [MIT licensed](LICENSE). Fonts and reference material retain
their [third-party notices](THIRD-PARTY-NOTICES.md). HyperFrames, GSAP, Chromium
and FFmpeg are separately installed dependencies with their own terms.
