# A feature and its video in one run

Taskfilm does the filming after the coding agent checks the real backend/UI
change. It does not implement the feature or infer acceptance from a video.
The optional feature skill keeps both deliverables in the same conversation:

```bash
taskfilm skill ~/.codex/skills/taskfilm-feature-explainer --name taskfilm-feature-explainer
```

Ask the agent to finish the change and include a Taskfilm walkthrough in its
final reply. When useful and authorized, it can assign the checked film to one
temporary worker while it completes independent work. The worker receives paths
and the checked revision, rather than the whole conversation. No helper is needed
when filming is the only remaining work.

## Run once

Start the real app through its existing recipe and keep that build stable during
capture. Write `capture.json` using the schema supplied by `taskfilm init`.
Include before/action/result beats, real interactions, and at least one `assert`
step with the expected DOM text and a unique screenshot name. Hold the final
result long enough to read. Keep backend test results with the feature handoff.

```bash
taskfilm run capture.json --out feature-film --revision filter-v2 \
  --source src/api/tasks.py --source src/ui/TaskList.tsx --json
```

Replace source paths with the files relevant to the task. Tracked files are
hashed before and between stages, including uncommitted changes. Taskfilm cannot
prove which live build a URL serves or detect every server/data change: keep the
target fixed and retain its build identity with the acceptance evidence.

The command validates the script, checks the browser, records exactly one take,
verifies every expected assertion and screenshot hash, prepares the edit and
editable HyperFrames composition, and fully decodes the finished movie.
It extracts full-size review frames and a contact sheet at the opening, beats,
assertions and ending, capped at twelve images. It keeps the exact take path;
it never searches for a global latest recording.

The default `--render-mode capture` preserves the recorded pixels, cursor and
click feedback at the captured viewport size and natural speed. It adds an
editable MP4 subtitle track and VTT captions, and moves MP4 metadata forward
for playback. It does not encode the video again or launch a second browser.
The local preview shows the timed explanations through native captions. Some
video players require enabling subtitles; the editable composition can burn
the explanations into a motion render when that is the desired output.

Use `--render-mode hyperframes --quality looks` for a rendered composition,
or choose `delivery` for the requested delivery encode. Supplying `--quality
looks` or `delivery` alone selects HyperFrames as well. Changing modes or quality
on resume reuses capture, edit and composition. The renderer keeps Taskfilm's
existing pin; there is no implicit runtime upgrade. Fast capture mode requires
FFmpeg/FFprobe and the browser extra, while motion rendering also needs Node/npm.

## Read the small result

Progress goes to stderr; `--json` writes one compact JSON result to stdout.
Stage logs stay in `feature-film/logs`. The result contains:

- `status`: `rendered` (movie prepared and decoded), `blocked`, `stopped`, or `stale`.
- `render_mode`: `capture` or `hyperframes`.
- `capture_verified` and `video_verified`: technical checks completed.
- `visual_review` and `audio_review`: separate review states, never inferred
  from successful execution. Silent output has `audio_review: not_applicable`.
- `artifacts`: exact MP4, editable project, take, checked result image, review
  frames, contact sheet, captions, and `preview.html` paths.
- `report`: the atomic `run.json` with stage timings and retained output hashes.
- `reused`: completed stages reused on this invocation.
- On failure, the phase, concrete error and relevant log path.

Inspect the checked result image and full-size movie frames. Listen to supplied
audio before claiming it reviewed. Include the MP4 or supported playable
attachment, preview link, result image, usage steps and feature acceptance
result in the same final feature response. A `rendered` receipt is not a visual
review. The HTML preview uses native playback and a text version of the beats;
local file playback in a chat depends on that client's attachment support.

## Resume without another take

If rendering failed, fix the reported cause and repeat the original command
with `--resume`. All input flags, including tracked sources and revision, must
match. An unchanged successful run reuses every stage. Changing only quality
reuses capture, edit and composition, then makes one new movie and review set:

```bash
taskfilm run capture.json --out feature-film --revision filter-v2 \
  --source src/api/tasks.py --source src/ui/TaskList.tsx \
  --resume --quality looks --json
```

Completed stages are reused only while all their retained output hashes match.
Missing or modified evidence is a failure. A changed product revision or script
requires a new output folder; previous versions and partial attempts remain
available. A source change during filming marks the run stale and stops the
next stage. Do not deliver that film as the new revision.

Each external command has a five-minute deadline, configurable with `--timeout`.
Interruption/timeout terminates that command's process group on POSIX, retains
partial files and releases the run lock. Concurrent runs cannot own the same
output folder. After an uncatchable process kill, confirm the previous job is
gone before manually removing its `.run.lock`. A retry is an explicit invocation,
not a background watcher or an automatic loop.

For custom narration, motion, trimming, or a manually edited composition, use
the individual `capture`, `edit`, `compose`, `motion` and `render` commands.
Keep original takes; iterate the film without repeating a valid product task.

If acceptance work already produced a verified Taskfilm take, pass `--take TAKE`
on a new run. The script bytes and every assertion must match. The agent must
also confirm that the take shows the requested running build; source hashes
recorded now cannot retroactively establish that. Taskfilm copies the verified
recording inputs into its own output folder, preserves the complete original
bundle and edit plan, and reports its path as `source_take`. Native exports
remain in that original bundle. No browser recording runs on this route.
