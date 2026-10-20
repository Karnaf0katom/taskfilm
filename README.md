# Taskfilm

**Make short videos that teach people how to use your software.**

[![CI](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml/badge.svg)](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Build a feature, then show people how to use it. Taskfilm records a real browser
workflow, prepares a captioned video and keeps an editable HyperFrames project.
Use it for feature handoffs, onboarding, release notes and tool walkthroughs.
Run the local CLI yourself or give its included skill to your coding agent.

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
guide. Follow the [workflow guide](docs/WORKFLOWS.md) and install the
[included agent skill](skills/taskfilm-video/SKILL.md) to adapt it to your app.
Installing a skill does not install a background watcher.

Install the packaged [feature-explainer skill](skills/taskfilm-feature-explainer/SKILL.md)
from Taskfilm **0.1.0a3** to include implementation, checks and the walkthrough in
one agent run:

```bash
taskfilm skill ~/.codex/skills/taskfilm-feature-explainer --name taskfilm-feature-explainer
```

The destination must be new; retain local customizations before replacing an
older installed skill. See the [one-run guide](docs/AGENT-RUN.md) for optional
background filming, reusable takes and the final video handoff.

## What you get

- **Real browser recordings** with timed actions, clicks, DOM assertions and hashed result screenshots.
- **Three story modes:** teach a feature, promote a product, or explain an OSS tool with pinned source attribution.
- **Editable motion:** camera moves, kinetic type, perspective, click effects, recap shots and original synthesized sound.
- **Your source files:** the original take, edit decisions, HTML/SVG composition and rendered MP4 stay local.
- **An agent skill** that uses the same CLI commands as you.

The sample needs no account, API key, GPU or model download. The fast handoff
prepares the recorded video locally. Optional motion rendering downloads the
pinned HyperFrames runtime and GSAP; an offline motion render is not promised.

## Install

Requires **Python 3.10+**. Capture needs **FFmpeg/FFprobe** and **Chromium**;
optional motion rendering needs **Node.js 22+** and **npm**. Linux is the checked platform for
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

Install or upgrade to the wheel from [Taskfilm 0.1.0a4](https://github.com/Karnaf0katom/taskfilm/releases/tag/v0.1.0a4).
Use `python -m pip install --upgrade` with the downloaded wheel, then check
`taskfilm --version`. Distribution is through GitHub Releases; PyPI publication
is not configured.

## Make your first film

The included Taskboard is an original local app. This recipe adds a task,
marks it complete and shows the result. Tasks use browser local storage.

```bash
taskfilm init demo
python -m http.server 8765 --bind 127.0.0.1 --directory demo/taskboard
```

Keep the server running. In another terminal with the same environment:

```bash
taskfilm run demo/capture.json --out lesson --json
```

Open the reported `artifacts.preview` to watch the captioned movie. The JSON
also links the checked result, review frames, original take and editable
HyperFrames project. Use that project path to change the composition, and
`--render-mode hyperframes` when you want a motion render. Keep the original
take so you can revise the film without repeating the task.

For a directed product promo or the original 24-second animation study,
follow the [motion recipes](docs/WORKFLOWS.md).

For a narrated app showcase, use the [Excalidraw motion-promo recipe](docs/WORKFLOWS.md#make-a-narrated-excalidraw-motion-promo).
It combines a real workflow with masked type, a perspective reveal, camera
choreography and animation of the saved diagram. Bring narration and a licensed
score; the CLI does not call ElevenLabs or another provider itself.

## Plan the story

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

## One run: checked feature to video

After your agent finishes and checks a backend/UI change, it can make the
walkthrough before its final response:

```bash
taskfilm run capture.json --out feature-film --revision feature-v2 --json
```

The command records the real app, verifies result assertions, and returns a
checked MP4, playable local preview, result image and review frames. The fast
default preserves recorded pixels and adds editable subtitle captions without
another encode or browser render. It also retains an editable HyperFrames
project. Choose `--render-mode hyperframes` for motion or burned-in explanations;
`--quality looks` or `delivery` selects that renderer too. Logs stay on disk,
and `--resume` reuses unchanged completed stages. The agent still inspects the
result and movie before delivery.

Install the implementation-and-video workflow with:

```bash
taskfilm skill ~/.codex/skills/taskfilm-feature-explainer --name taskfilm-feature-explainer
```

It keeps backend/UI checks and the film in the same final handoff, with one
optional temporary filming worker when authorized and useful. See the
[one-run guide](docs/AGENT-RUN.md) for source tracking, resume and output details.

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

```bash
taskfilm skill ~/.codex/skills/taskfilm-video
```

Choose the skill folder used by your agent. Existing destinations are never
overwritten. The [included skill](skills/taskfilm-video/SKILL.md) explains the
capture, composition, motion and evidence workflow; it requires no private checkout.

## Commands

| Command | Purpose |
| --- | --- |
| `run` | Capture, compose, render and return a resumable feature-video handoff |
| `doctor`, `init`, `skill` | Check tools, copy samples and install the skill |
| `story` | Plan a feature lesson, promo or OSS walkthrough |
| `capture` | Validate, discover and record a browser workflow |
| `edit` | Prepare edit decisions from a take |
| `compose`, `reel` | Create landscape or portrait HTML compositions |
| `motion` | Author the directed product-film kit |
| `render` | Check and render with pinned HyperFrames 0.8.134 |
| `repo-pack` | Retain pinned repository source and attribution |
| `package` | Package evidence or checked films and downloads |

Run `taskfilm COMMAND --help` for each input contract.

## Privacy and scope

Capture uses a fresh browser context by default. Keystroke event logs redact
characters, but the screen still records visible text. Review footage before
sharing. Keep authentication state, cookies and browser profiles outside your
take bundles and repository. Run capture scripts and setup JavaScript you trust.

This alpha provides a local CLI and editable compositions. Hosted orchestration,
provider-generated media, a timeline editor, repository sandbox execution and
Adobe After Effects project import are outside its scope. Source assertions,
capture checks and final visual review remain separate evidence.

## Contribute

```bash
python -m pip install '.[browser,motion,dev]'
python -m pytest -q
# Optional real-browser task; requires FFmpeg and installed Chromium.
TASKFILM_BROWSER_TEST=1 python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
[RELEASE.md](RELEASE.md). CI tests installed wheels and source distributions
outside the checkout, records the original browser task, and checks audio
through a complete HyperFrames render.

## License

Original code is [MIT licensed](LICENSE). Fonts and reference material retain
their [third-party notices](THIRD-PARTY-NOTICES.md). HyperFrames, GSAP, Chromium
and FFmpeg are separately installed dependencies with their own terms.
