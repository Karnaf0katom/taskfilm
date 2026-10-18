# Feature walkthrough production

For demos during feature work or background filming, also use
[the in-chat workflow](in-chat.md). It defines readiness, revisions and controls;
the commands below remain the production path.

For the default browser feature lesson, use `taskfilm run SCRIPT --out FILM --json`
after the feature's acceptance checks pass. It prepares a captioned MP4 from the
real recording without a second encode, plus the editable HyperFrames project,
exact artifact paths, technical receipts and review frames. Use `--resume`
with unchanged inputs after a failed render. The manual stages below are for
custom direction, narration or debugging; they are not an additional required pass.

## Inputs and output folder

Use the finished diff or commit, passing acceptance evidence, the actual app
URL or executable, and the user's language and audience. Resolve the product's
existing build/start recipe rather than creating a replica. Keep the lesson in
the product's existing artifact location or a new local output folder outside
its source tree. Do not overwrite an earlier take or delivery.

Retain a small `FEATURE-WALKTHROUGH.json` record with the feature identity,
starting state, steps, success condition, check commands and results, exact take,
composition and movie paths, and their SHA-256 values. Record capture verification,
render completion, visual review and audio review separately. A review can be
`not_performed`; silence can be `not_applicable`. Add a concrete blocker when
a required stage cannot finish. For an ongoing build, also retain the revision,
source/build fingerprint, phase, helper id when used, and known execution handles
needed for cancellation. Keep credentials out of the record.

## Browser task

Check the installation and actual contracts:

```bash
taskfilm doctor
taskfilm capture check
taskfilm capture --help
taskfilm story --help
taskfilm init feature-film/sample
```

`init` creates the original Taskboard sample and editable request, story and
capture files. Adapt their schemas to the real target. The Taskboard is useful
for checking the tools; it is not evidence for another app's feature.

Use `feature_demo` in the story file. Bind each claim to its source or runtime
evidence and each moment to a concrete before/action/after task. State the
feature's benefit in the opening. The request's declared evidence references
are planning inputs, not completed capture checks.

Build `feature-film/capture.json` from the bundled capture schema:

- Set the real `url`, `viewport` and a stable `wait_for` selector.
- Place `beat` steps before the actions they explain. `explain` is visible text;
  `vo` is a narration script and does not generate a voice.
- Use real `click`/`type`/`wait_for` actions and natural reading holds.
- Include `assert` steps with a selector, exact expected `text` and a unique
  `.png` screenshot filename. Assert the state that proves the feature worked.
- End with a result explanation and a readable hold, followed by a useful
  next action in the caption or final handoff.

Validate, plan and record through the existing owners:

```bash
taskfilm capture validate feature-film/capture.json
taskfilm story --request feature-film/sample/request.json \
  --story feature-film/sample/feature.json --brand-dir feature-film/sample/brand \
  --out feature-film/story-plan
taskfilm capture rec feature-film/capture.json --out-dir feature-film/takes --no-burn-captions
```

Select the exact take directory printed by the recorder. Never guess a
timestamp or pick an unrelated latest recording. Check `session.json`:
all scripted steps must succeed, `streams.screen.status` must be `ok`, and
every expected assertion must have a `passed` receipt. Resolve each receipt's
screenshot beneath that take, verify its SHA-256, and inspect the actual result.
The full screen recording must be nonempty. Stop on a failed assertion.

Prepare a lesson with the whole UI visible. In these commands, `TAKE` means
the exact directory from that recording, substituted by the agent:

```bash
taskfilm edit TAKE --no-retime --no-aim
taskfilm compose TAKE --out feature-film/composition --no-title \
  --width 1280 --height 720 --max-scale 1 --note-top 4 --keep-dead-air
taskfilm render feature-film/composition --output feature-film/walkthrough.mp4 --quality draft
```

The composition uses the recorded beat labels. Inspect the resulting HTML and
story plan, and apply any missing introduction, instructions or result hold.
For a custom scene, use the installed HyperFrames composition guidance when
available, or the generated project's contract and checked examples. Keep its
pinned runtime for this Taskfilm alpha; do not silently change the renderer.
Retain the font notices and the original take. After delivery-size visual review,
use the requested render quality and a new output filename for the final encode.

## Command or backend task

Use the project's existing acceptance command in a controlled local/test
environment. Save the command, exit code, actual output and observable result.
Explain only what that evidence supports. A command transcript can appear as
readable excerpts in an editable composition; do not describe such graphics as
a recording of a GUI. Show the input and result with enough context to repeat
the task. Preserve local execution and permission rules for the target project.

## Review and deliver

Probe and completely decode the encoded movie, then inspect frames at the
opening, the actions and the held result. View at the intended delivery size;
labels and controls must remain readable. For narrated output, listen to the
complete encoded audio as well. Check that the explanation matches the actual
workflow and that the result visible in the film matches the acceptance evidence.

The final feature response should link the movie and editable source, give the
minimum usage steps, and name the acceptance result. Keep a local checked
feature, a captured task and a reviewed delivery distinct. Publish only to a
destination already authorized by the user.
