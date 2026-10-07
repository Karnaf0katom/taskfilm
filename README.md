# Taskfilm

**Turn real workflows into editable product films.**

[![CI](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml/badge.svg)](https://github.com/Karnaf0katom/taskfilm/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Taskfilm records a browser task, retains its actions and result evidence, and
turns the footage into editable HTML motion graphics with HyperFrames. Make
a feature lesson, a product promo, or an open-source walkthrough from a real
working product. Run it from a terminal or give its included skill to your agent.

[Watch the examples](https://karnaf0katom.github.io/taskfilm/) ·
[Download the release](https://github.com/Karnaf0katom/taskfilm/releases) ·
[Workflow guide](docs/WORKFLOWS.md)

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

You can also install the wheel from the
[GitHub release](https://github.com/Karnaf0katom/taskfilm/releases). There is no
PyPI release yet.

## Make your first film

The included Taskboard is an original local app. This recipe adds a task,
marks it complete and shows the result. Tasks use browser local storage.

```bash
taskfilm init demo
python -m http.server 8765 --bind 127.0.0.1 --directory demo/taskboard
```

Keep the server running. In another terminal with the same environment:

```bash
taskfilm capture validate demo/capture.json
taskfilm capture rec demo/capture.json --out-dir takes --no-burn-captions

# Replace YOUR-TAKE with the timestamped directory printed by the recorder.
taskfilm edit takes/YOUR-TAKE --no-retime
taskfilm compose takes/YOUR-TAKE --out lesson --no-title \
  --width 1280 --height 720 --max-scale 1 --note-top 4
taskfilm render lesson --output lesson.mp4
```

Edit `lesson/index.html` to change the composition. Keep the original take so
you can revise the film without repeating the task.

For a directed product promo or the original 24-second animation study,
follow the [motion recipes](docs/WORKFLOWS.md).

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
