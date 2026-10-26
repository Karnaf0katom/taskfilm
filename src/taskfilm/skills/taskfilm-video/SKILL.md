---
name: taskfilm-video
description: Record real product tasks, coordinate full courses with narration and personal voiceovers, author directed product films, or edit the included HTML/SVG animation study through Taskfilm and HyperFrames. Compose branded ads with narration, music, captions and optional presenters, edit them in Studio, or schedule posts to configured social accounts. Use for courses, feature lessons, ads, motion promos and source-attributed OSS demos. Repository sandbox builds are outside this alpha.
---

Use the installed `taskfilm` CLI. Read its README for installation and run
`taskfilm doctor` and `taskfilm capture check` before browser capture. This skill
is self-contained and does not require the private monorepo or fleet tools.

For an end-of-upgrade lesson, use the focused `taskfilm-feature-explainer`
skill when installed. It can also accompany UI/feature work, select checked
milestones, and return a requested background demo to the same chat with stop
and change controls. Install it with `taskfilm skill DIRECTORY
--name taskfilm-feature-explainer`; it includes its production reference.

Choose the story treatment from the user's goal: `feature_demo` for one
repeatable task, `saas_launch` for problem/workflow/payoff and a supplied CTA,
`github_review` for a pinned OSS source with fit, limitation and attribution.
`taskfilm init demo` supplies an original working app, capture script and sample
request/story files. Adapt its inputs instead of inventing unsupported flags.
Read `taskfilm story --help` and `taskfilm capture --help` for the actual contracts.

For a full course, read `docs/COURSES.md` and use the bundled `course.json` outline.
Author the curriculum from the supplied materials: identify the intended learner,
an observable final skill, prerequisites, ordered modules and one practical outcome
per lesson. Write each lesson's explanation, demonstration, exercise and success
criterion. Ground factual and product claims in supplied sources and observed
results; missing facts or application access remain explicit inputs.
Run `taskfilm course init DIRECTORY --outline FILE`, prepare or acquire each
lesson's recording, and use `course build` to render the series. Browser capture
scripts need visible-result assertions. Optional `course narrate --voice-id ID`
uses the caller's own ElevenLabs environment key; `course voiceover --lesson ID
--audio FILE` imports a human read. Keep existing personal reads unless explicitly
asked to replace them. Keep instructor examples in the lesson notes and authored
scripts, preserve their edits, and inspect the films before recording a review.
Use `course status` to resolve blockers and `course package --out FILE` to deliver
current films with learner guides and practice resources. Work through the course
autonomously where the inputs suffice. A planned project is not a rendered lesson,
and a rendered lesson is not evidence that someone reviewed its teaching accuracy.

For the first installation check, run `taskfilm demo my-first-film` in a new
directory. It starts and stops its own local Taskboard server, records the
original sample task, verifies result screenshots and prepares an editable
lesson. Its `DEMO-RESULT.json` names the exact take, composition and logs.
When a rendered trial is requested, add `--render`; `--quality draft` gives a
faster trial encode. Review the finished movie before sharing. To demonstrate
another app, adapt the manual sample workflow below rather than describing
the original Taskboard as that app.

For an original Taskboard product-promo trial, use `taskfilm demo my-product-film
--mode promo --format both --render --quality draft`. The `motion` extra is
required. This recipe measures a single 4K take and calls the existing motion
owner for separate landscape and portrait projects with synthesized audio.
Omit `--render` to prepare the editable cuts first; `DEMO-RESULT.json` lists
each deliverable and its edit decisions. It does not record another product
or establish that a finished movie has passed visual review.

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

For a wider original-animation repertoire, run `taskfilm treatments --brief
"THE SUBJECT AND IDEA" --seed 41` and choose between `type-sculpture`,
`orbit-story` and `signal-field`. `taskfilm animate NEW-PROJECT --treatment ID
--headline "SHORT COPY"` actually authors the selected recipe; render with
`taskfilm render`. `--showreel` produces an 18-second three-family study;
`--format portrait` authors a separate portrait layout. Audio reuses the existing
original score owner and needs the `motion` extra; `--silent` omits it.
Read `docs/ANIMATION.md`. Use the same brief/seed/history for selection and
authoring; `--history` excludes recently reviewed structures, and `--allow-repeat`
is an explicit series override. Planning and authoring never record a delivered
film. Review encoded frames and audio before adding a hash-bound history event.

`taskfilm init demo` includes `demo/brand.json`; pass it with `animate --brand-file`
to reuse supplied copy and palette. Explicit flags override the file. After an
actual review, `taskfilm record-review PROJECT --movie FILM.mp4 --history HISTORY.json
--reviewer "REVIEWER" --confirm-reviewed` records that caller's declaration and
actual media/plan hashes. Do not use it to turn a successful render or probe into
a claim that a person reviewed the film. See the brand-file and review-history guides.

For ads, use `taskfilm ad` rather than repeating the fixed motion layout. Supply
the product's actual logo, local fonts and colors in `taskfilm-ad/v1`; retain
real source footage. `ad templates`, `ad plan` and `ad build` support eight
layout families, external declarative templates, product/style matching and
local history/ratings. Crop in source pixels; `media.speed` accelerates source
time without replacing the real interaction. Keep results readable at delivery
size. Read `docs/AD-DIRECTION.md` for composition and presenter contracts.

Use `media narrate --provider google --voice Kore` for Google Gemini speech
generated directly from the current server, using `GOOGLE_API_KEY`, `GEMINI_API_KEY`
or a server-owned `TASKFILM_GOOGLE_KEY_REF`. Keep keys outside versions and receipts.
Local/SSH Mac speech and optional video-claw providers are also supported;
API calls use the configured account's quota and credit. Use
`media music` to choose/fetch licensed tracks, and `media mix` for timed speech,
ducked music, attribution receipts and captions. No SFX is the default; effects
are limited to two types/four events. `media avatar` optionally generates a
lip-synced presenter through video-claw. Compose a finished mix via `audio.path`,
render, then `media finish` can burn timed captions or overlay a presenter.
Read `docs/ADS.md` and command help for the exact flags and schemas.

`publish enqueue` stores a scheduled post in a durable local queue; include its
`audio_receipt` to carry music credits into the caption. `publish work` previews
without sending; `work --execute --watch` processes due jobs automatically.
Read `docs/PUBLISHING.md` for platform credentials and account IDs. Respect the
user's existing destination/scheduling authorization; recurring authorized
posts do not need per-post reconfirmation. An ambiguous provider write becomes
`needs_review`; verify the remote result before reconciliation or a new post.

For visual editing and stage resume, import an existing ad/audio project with
`taskfilm studio import WORKSPACE --ad ad.json --audio audio.json`, then run
`taskfilm studio serve WORKSPACE`. For multiple projects, register each workspace
with `taskfilm studio register LIBRARY WORKSPACE --id PROJECT` and serve with
`taskfilm studio serve LIBRARY --library`. The Projects home opens isolated editors,
creates drafts and duplicates complete projects without API generation. Every save and completed stage keeps a full
portable version with source files, editable plans and available outputs.
Download or restore any version; do not modify sealed versions directly.
Copy/crop/layout edits reuse capture and narration. Audio edits regenerate only
changed lines and reuse the visual render. Voice provider, name and speaking speed
can be edited in Audio; they invalidate Audio and Render without rebuilding Composition. Update stages marked stale in order.
Studio Publish prepares a release; it does not execute live posts. Read
`docs/STUDIO.md` for imports, exports, capture limitations and resume behavior.

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
