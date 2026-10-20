# Adaptive capture with OpenGCUA

`taskfilm capture gcua` records a trusted Python program using the optional
[OpenGCUA SDK](https://github.com/Tongyi-MAI/OpenGCUA/tree/v0.1.2/packages/sdk).
Use it when a workflow needs conditional actions, accessibility targets, canvas
coordinates, or a combination of those and Playwright. The program drives a real
browser and leaves the same take that `taskfilm edit`, `compose` and `reel` read.

## What this adds

Taskfilm already has deterministic browser scripts, semantic selector discovery,
coordinate clicks and drags, native result assertions, timed input, narration
beats, editing and rendering. Replacing those with an entire agent harness would
duplicate working capabilities.

| Capability | Existing Taskfilm | This integration |
|---|---|---|
| Fixed, repeatable browser lesson | `capture rec` JSON script | Keep the existing route |
| Branches, loops and recovery based on actual state | An agent authors another script | One trusted async Python program |
| Accessibility and visual reference validity | Selectors and explicit coordinates | OpenGCUA's observed/delivered AX nodes and image points |
| Mix DOM, accessibility and visual actions | Separate capture steps | Native SDK handles in the same program |
| Take, input timing, narration, result evidence | Existing capture contract | Reuses that contract and FFmpeg encoder |
| Edit, captions, motion and film rendering | Existing owners | Same downstream commands |
| Desktop/mobile, model training, agent service | Outside this CLI | Outside this integration |

The SDK is a research preview. This adapter supports **qwen-intelligence-sdk
0.1.2**, pinned to upstream commit
`b753f4c645b499e362d70303c23c26bd4ce24937`. It imports the public
`qwen_intelligence.Runtime`; upstream owns its native runtime and drivers.
No upstream code is copied into Taskfilm. OpenGCUA is Apache-2.0 licensed;
this original adapter retains Taskfilm's MIT license.

## Install the optional driver

Keep the normal Taskfilm installation. This mode additionally requires **Python
3.11–3.14**, Node.js 22+, FFmpeg and the SDK's Chromium worker. Ordinary Taskfilm
commands retain their Python 3.10+ requirement and need no SDK.

Download the wheel matching your Python, OS and architecture from the
[OpenGCUA v0.1.2 release](https://github.com/Tongyi-MAI/OpenGCUA/releases/tag/v0.1.2),
then install it in the same environment as Taskfilm:

```bash
python -m pip install /path/to/qwen_intelligence_sdk-0.1.2-MATCHING-TAGS.whl
mu setup browser --engine chromium
mu doctor browser --engine chromium
taskfilm capture gcua --help
```

For CPython 3.11 on Linux x86_64, the released wheel is
`qwen_intelligence_sdk-0.1.2-cp311-cp311-manylinux_2_28_x86_64.whl`, with SHA256
`d4dd0f3fcdb7ab9f59dd8b68222df8458d8d42f61d1505a5a989ef67f2eb117b`.
Prebuilt wheels avoid Rust compilation. Windows and the other SDK platforms
are not verified by this adapter. No model, account, API key or GPU is needed
for the included workflow.

## Record the bundled task

```bash
taskfilm init demo
python -m http.server 8765 --bind 127.0.0.1 --directory demo/taskboard
```

Keep that server running and, in another terminal:

```bash
taskfilm capture gcua demo/opengcua-taskboard.py \
  --url http://127.0.0.1:8765/ --out takes/adaptive-taskboard
taskfilm edit takes/adaptive-taskboard --no-retime
taskfilm compose takes/adaptive-taskboard --out adaptive-lesson
taskfilm render adaptive-lesson --output adaptive-lesson.mp4
```

The original Taskboard example adds a task via AX and Playwright, completes it
conditionally, and selects the Completed filter using an observed image point.
Three exact visible-text assertions retain hashed result screenshots. Review the
finished movie before sharing it. A passing DOM assertion does not certify the
film's visual quality.

## Write a workflow

The file defines `async def run(tab, film)`. `tab` is the real OpenGCUA tab,
with its native `ui.ax`, `ui.vision`, `playwright`, `evaluate` and navigation APIs.
`film.mu` is its session. SDK operations and any external calls your program
makes are ordinary trusted Python running with your host access.

```python
import asyncio

async def run(tab, film):
    film.beat("add", vo="Add a task and check that it appears.")
    observed = await film.observe()  # AX observe + explicit mu.emit
    field = next(node for node in observed.tree.nodes if node.name == "Task title")
    await tab.ui.ax.click(field, timeout_ms=15000)
    await tab.playwright.get_by_label("Task title").fill("Ship the demo")
    await tab.playwright.get_by_role("button", name="Add task", exact=True).click()
    await film.assert_text("#tasks li span", "Ship the demo", screenshot="added.png")
    await asyncio.sleep(2)  # give the viewer time to read the result
```

`film.beat(id, vo=..., explain=..., show=..., lang="en")` marks the existing
narration stream. `film.assert_text(selector, text, screenshot=..., timeout=15)`
requires one visible matching element and exact visible text. A failed assertion
keeps the take failed even if the program catches its exception. Screenshots
never overwrite earlier evidence. `film.observe()` observes and emits the AX
tree; explicit `film.mu.emit(...)` observations are saved beside the take.

Re-observe after state changes rather than reusing old node indices. For visual
actions, emit the observation and use a point from its own image, as shown in
`opengcua-taskboard.py`. `film.observe()` allows 15 seconds by default rather
than the SDK's 1.5-second browser default; CPU-only hosts can need several
seconds for an AX capture. Pass `timeout_ms` to change this budget. Taskfilm
does not weaken the SDK's delivery or staleness
checks. The recorder's screenshots use the separate Playwright bridge and do not
replace the program's live SDK observations.

The coding agent can generate a program with branches and loops. This command
does not run a model planning loop or install the upstream macOS harness. It
does not select a provider or reconnect any existing account.

## Evidence, recording quality and limits

- The SDK creates one fresh browser context and recorded tab. Existing signed-in
  browsers and CDP attachment are not supported in this mode. The released
  worker does not implement the connection options exposed in the Python API.
- Capture uses real screenshots of that tab, sampled at a requested **8 fps**
  by default (`--fps 1..15`), then encoded at 30 fps by the existing FFmpeg owner.
  Sampling can slow during SDK operations. Use `capture rec` for smooth native
  screencasts, fast motion or known deterministic workflows.
- DOM input logs cover the recorded tab's main frame. They retain actual event
  timestamps and redact typed characters. Programmatic field edits are not
  keystrokes. Navigation can discard pending events; the manifest marks input
  coverage partial if the final document differs from the starting document or
  the 5,000-event queue overflows. The tap is installed before the program and
  drained afterward: the SDK treats evaluation as a write, so background capture
  only calls its read-only screenshot API. A full navigation removes the tap;
  keep one document for complete input coverage. Iframes and other tabs are
  outside input coverage. Pixels still contain visible text.
- Keep actions in the supplied tab and viewport. A changed viewport fails
  capture. The default program deadline is 120 seconds (`--timeout 1..600`).
  A recorder failure cancels the program; failures keep available footage and
  `session.json` with a failed driver status.
- `session.json` retains the exact executed program's hash and basename, SDK
  version/commit, capture method, assertion receipts and verification state.
  The program's source, credentials and model conversations are not copied.
  Explicitly emitted AX text and images are local observation artifacts.
- A successful capture without assertions has `result_verification: not_verified`.
  Final visual verification always starts as `not_performed`.

## Verify changes

The optional SDK test runs the original local Taskboard with AX, Playwright and
visual actions, probes the actual MP4, verifies the screenshot hashes and checks
that the existing edit planner reads the take:

```bash
python -m pytest -q tests/test_opengcua_capture.py
TASKFILM_GCUA_TEST=1 python -m pytest -q tests/test_opengcua_capture.py
```

The default tests check validation, preserved outputs, missing/incompatible SDK
handling, recorder failure, program cancellation and failed assertion evidence.
Native capture is an opt-in integration check, independent of the normal browser
test and of final film review.
