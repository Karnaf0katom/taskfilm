---
name: taskfilm-feature-explainer
description: Deliver backend and UI changes with a real Taskfilm video in the same agent run and final response. Use when a user requests a feature walkthrough with implementation, including optional authorized background filming.
---

Finish the requested backend/UI change, check it, and deliver a readable video
of one useful workflow before ending the same conversation. A requested film
is part of the feature handoff; do not stop at offering to make it later.
Use the user's language and the real product's labels and appearance.

## One implementation, one capture, one render

Use the project's existing build/start and acceptance commands. Keep their
results with the feature record; passing browser assertions alone do not prove
backend tests passed. Coalesce related edits into one stable milestone. Prepare
the capture while building, then keep its running target unchanged during filming.

Write a capture JSON for the actual app: short `beat` explanations around real
actions, an `assert` with a screenshot for the useful result, and a readable final
hold. Use `taskfilm init` only when the capture schema is unknown; its Taskboard
is a tool fixture, never evidence for the changed product.

```bash
taskfilm run feature-film/capture.json --out feature-film/run-1 \
  --revision FEATURE-REVISION --source path/to/backend.py --source path/to/ui.tsx --json
```

Substitute real relevant files. Track relevant uncommitted sources, capture
inputs and running build identity; HEAD alone is insufficient. The CLI checks
tracked file hashes between stages; it cannot detect every live server/data change.
The fast default keeps the recorded pixels, cursor and click feedback, adds
editable subtitle captions, and prepares MP4 playback without another encode
or browser render. The preview shows the timed explanations. The clean take
and editable HyperFrames project stay available. Use `--render-mode hyperframes`
for motion or burned-in explanations; `--quality looks` or `delivery` also
selects that renderer. Choose the requested treatment up front, without a
routine draft-plus-final cycle. If a checked take already exists, `--take TAKE`
imports its verified inputs without recapturing; confirm its running revision.

The command writes stage logs to disk and returns compact JSON with the exact
take, editable project, MP4, result image, review frames and playable preview.
Read that result instead of loading logs or composition source into context.
On failure inspect only the reported log's relevant tail. Repeat the same command
with `--resume` after fixing the cause: completed unchanged stages are reused.
Changed product/capture inputs require a new output folder. A render failure
does not require repeating the product task. Do not start a polling service.

Inspect the result screenshot and full-size review frames, and check audio when
present. `status: rendered` means assertions, encoding and decoding passed;
`visual_review: not_performed` still requires the agent's review. The preview is
local HTML with native playback; it does not publish the files.

Read [the production reference](references/workflow.md) for capture authoring,
custom films or backend-only tasks. Read [the in-chat workflow](references/in-chat.md)
only for background delegation, revisions during filming, or stop/change controls.

## Optional background filming

When the user authorized delegation and independent implementation/checks remain,
use at most one temporary worker with `fork_turns: none`. Give it only the checked
capture, actual target/reset recipe, passing checks, source/build revision, owned
output folder and this skill. One deliverable: run the CLI and review the film.
One acceptance check: the scripted task and reviewed movie match that revision.
Request a final report of status, artifact paths, checks and concrete blocker;
no source edits, publishing, grandchildren or transcript streaming. The parent
collects that result before its final answer and rechecks the target revision.
If no independent work remains, run in the owning conversation; delegation
has a context/startup cost. Installing this skill does not authorize helpers.

A feature change during filming stops the affected job and invalidates its
result. Copy or pacing changes can reuse a valid take. Stop/pause requests stop
the requested work and its known processes; do not automatically restart them.
After two attempts hit the same unchanged blocker, retain partial files and
report the concrete resume condition.

## Same-response handoff

Include the movie or playable attachment, local preview, readable result image,
editable project and the feature's acceptance result in the final feature reply.
Use the chat's attachment capability when available; otherwise link the exact
files. Do not promise inline local MP4 playback in every client. Give the minimum
usage steps and state which revision was filmed. Keep implementation checks,
capture assertions, video decoding and human/agent visual review distinct.
For backend-only changes, execute the real command and retain its result; label
any explanatory diagram or transcript as such instead of fabricating a GUI.
