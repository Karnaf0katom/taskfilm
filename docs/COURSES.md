# Courses with an instructor's touch

Taskfilm can coordinate an ordered course: curriculum, lesson scripts, real
recordings, narration, editable cuts, rendered films, exercises and a learner
ZIP. Your agent authors the teaching material from your sources and runs the
production commands. You can add your own voice, examples and edits at any point.

This workflow is included in Taskfilm **0.1.0a5**.

## Start from what students should be able to do

Give your agent the subject, intended learners, source material and a concrete
end result. Ask it to prepare `outline.json` using the bundled `course.json`
example. Each lesson needs a module, objective, script, practice task and a
visible success criterion. Keep each lesson about one repeatable skill.

```text
Build a course from these materials for [learners]. At the end they should
be able to [observable result]. Use Taskfilm's course workflow. Prepare the
curriculum, scripts and practice activities, record the demonstrations, and
produce the lesson films and learner package. Keep my examples, recordings
and edits. Use the supplied voice configuration if narration is needed.
```

```bash
taskfilm init examples
# Your agent adapts examples/course.json into outline.json.
taskfilm course init my-course --outline outline.json
taskfilm course status my-course
```

The outline uses `schema: "taskfilm-course/v1"` and an ordered `lessons` list.
Course fields are `title`, `audience` and `language`. Lesson fields are `id`,
`module`, `title`, `objective`, `script`, `exercise` and `success_criteria`.
Use lowercase lesson IDs such as `first-wall`. An optional `resources` list
contains explicitly supplied practice files, each with `title` and `path`.

For each lesson supply either `source`, the path to an existing video, or
`capture`, the path to a Taskfilm browser capture script. An empty `source`
leaves the lesson waiting for a recording. Imported paths resolve relative
to the outline. You can update them in the generated `course.json`.

Browser capture reuses `taskfilm capture rec`; include at least one `assert`
step proving the visible result. Successful takes are retained and reused
until their script or media changes. Use `course build --recapture` for fresh
takes after the target application changes. Capture still needs the target app,
browser dependencies and any login you supply. Native applications such as
Revit use supplied recordings or the [Windows starter](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a4/Taskfilm-Revit-Starter.zip).
The course command does not autonomously control native applications.

## Produce the lessons

```bash
# Optional AI narration; this uses only your ELEVENLABS_API_KEY environment key.
# Choose a voice you have access to. Existing attached reads are kept.
taskfilm course narrate my-course --voice-id YOUR_VOICE_ID

# Prepare editable HyperFrames projects without claiming films were rendered.
taskfilm course build my-course --prepare-only

# Check, render and decode every current lesson. Unchanged films are reused.
taskfilm course build my-course --quality looks
taskfilm course status my-course
taskfilm course package my-course --out my-course.zip
```

Narration reuses the existing ElevenLabs provider seam, sentence chunker and
audio stitcher. It is an explicit opt-in command and uses your provider account;
ordinary recording and personal voice imports need no voice API key. Failed
reads keep prior audio. The source script and voice settings stay with the
read's receipt. Re-running `narrate` keeps personal recordings and current AI
reads. It regenerates AI reads when their scripts or voice settings change;
use `--replace` to explicitly replace a personal recording with an AI read.
Builds flag an AI read that no longer matches its script.

Rendering needs Node.js 22+, npm, FFmpeg and the existing HyperFrames runtime.
If HyperFrames reports that its cached Chrome cannot start, select an existing
working Chrome binary with the `HYPERFRAMES_BROWSER_PATH` environment variable.
If one lesson fails, the others can finish. The report names its failure and
log; rerun the same build after correcting its input. `--lesson first-wall`
limits production to one lesson. No build overwrites a previous take or film.

The package contains numbered lesson MP4s, learner guides, practice tasks,
supplied resources and a hash inventory. Preparation, stale films and failed
lessons cannot be packaged as current films. Source recordings, input traces,
logs and voice credentials stay in the working project. The ZIP is a learner
delivery, while the course directory retains the editable production project.

## Add your own teaching style

- Edit `lessons/ID/script.txt` to change the explanation. This is a script,
  not a transcript of recorded speech; regenerate or record a read to change
  the spoken words.
- Add personal examples in `instructor-notes.txt`; the agent can incorporate
  them into the script and demonstrations. Notes alone do not alter a film.
- Add your voice with `taskfilm course voiceover my-course --lesson first-wall
  --audio my-read.wav`. Previous reads remain in the lesson folder.
- Adjust `lessons/ID/edits.json` using the existing `taskfilm polish` edit
  format: cuts, trims, zooms, annotations, framing and optional speed changes.
  The default retains source timing. Keep instructional actions at natural
  speed unless a deliberate edit makes them easier to follow.
- Open the project path reported by `status` in HyperFrames to refine the
  timeline. A later build renders that edited project when its lesson inputs
  are unchanged, reading the editor's current duration and audio tracks for QA.
  If the source, script or edit specification changes, Taskfilm
  prepares a new project and retains the earlier one.

An attached voiceover replaces the source audio and begins at source time zero.
Cuts and speed edits then affect voice and picture together. It must fit inside
the original demonstration; a longer read requires a longer recording or a
shorter script. Taskfilm does not silently rush the instructor's voice.

Machine QA checks stream presence, planned duration and complete decoding.
Silent lessons carry an explicit warning. Teaching accuracy, pronunciation and
voice/action alignment require watching and listening. If an instructor reviews
a lesson, record that declaration against the current movie:

```bash
taskfilm course review my-course --lesson first-wall \
  --reviewer "Instructor name" --confirm-reviewed
```

Reviews bind to the exact film and lesson inputs. A change makes the old review
stale. Packaging can retain pending reviews; it never labels a successful encode
as an instructor's approval.
