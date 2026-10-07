---
name: taskfilm-video
description: Record real product tasks, author directed product films with the existing motion kit, or edit the included HTML/SVG animation study through Taskfilm and HyperFrames. Use for feature lessons, motion promos and source-attributed OSS demos. Provider-generated media and repository sandbox builds are outside this alpha.
---

Use the installed `taskfilm` CLI. Read its README for installation and run
`taskfilm doctor` and `taskfilm capture check` before browser capture. This skill
is self-contained and does not require the private monorepo or fleet tools.

Choose the story treatment from the user's goal: `feature_demo` for one
repeatable task, `saas_launch` for problem/workflow/payoff and a supplied CTA,
`github_review` for a pinned OSS source with fit, limitation and attribution.
`taskfilm init demo` supplies an original working app, capture script and sample
request/story files. Adapt its inputs instead of inventing unsupported flags.
Read `taskfilm story --help` and `taskfilm capture --help` for the actual contracts.

Keep before/action/result explicit. For a lesson, keep real interactions at
natural speed and hold the visible result long enough to read. Promos can cut
idle time, with a useful result still on screen. Use `taskfilm repo-pack` and
`story --repo-pack` for source-based OSS assertions; the source pack does not
prove runtime behaviour.

For the original Taskfilm OSS sample, `init` includes `oss.json` and
`prepare-oss-review.py`. Bind its request to the actual pinned public release
README using the recipe in the README, then use `story --repo-pack`. The helper
refuses README bytes that differ from the source pack. Other repositories need
their own source claims and real task actions.

Record with `taskfilm capture rec SCRIPT --out-dir takes --no-burn-captions`.
Use the exact take path it reports. `taskfilm edit TAKE --no-retime` prepares
the lesson edit. `taskfilm compose TAKE --out PROJECT` or `taskfilm reel TAKE
--out PROJECT` exports an editable composition from real footage and beat
labels. The story brief is direction to apply and inspect, not automatically
executed by the composition command. `taskfilm render PROJECT --output FILE`
checks and renders through the pinned HyperFrames owner.

For a directed motion promo, use the existing product-film owner: the sample
`motion-capture.json` records a real 4K take, and `motion-spec.json` supplies the
brand, copy, measured regions and action anchors. Copy the spec to `spec.json`
beside the film, then run `taskfilm motion FILM --take EXACT-TAKE --format landscape`
or `portrait`. Read `taskfilm motion --help`. Its optional NumPy/SciPy dependencies
are installed with the `motion` extra. The output under `FILM/cuts/FORMAT`
retains an edit-decision record; rendering stays with `taskfilm render`.

For pure motion graphics, `init` also supplies `motion-lab/`: four original
editable HyperFrames scenes with masked type, SVG drawing/interpolation and
perspective. Edit the scene files and their paused GSAP timelines, then render
that project. It is a silent animation study. Do not describe it as an Adobe
After Effects project importer.

`taskfilm package --showcase MANIFEST --out DIRECTORY` packages finished,
hash-bound movies and distribution downloads as a portable static release
preview. It probes movie metadata and retains hashes; it does not create or
approve a film. `package --evidence` retains the original take-companion contract.

Keep plans, capture success, verified product result and final-video review
distinct in your report. Inspect the result in the captured task, inspect
delivery-size video frames, and listen to complete audio when supplied.
Never treat a UI replica as proof. Use supplied/currently owned accounts and
media. Keep cookies and browser profiles out of examples and packages.
Publish only when the user has authorized the concrete destination/output.
