# Build a feature, then explain it

Use Taskfilm at a checked milestone while building a browser product. Your agent
records one useful task in the real app and turns it into a short, editable
walkthrough: what it does, how to use it, and the visible result.

Taskfilm **0.1.0a5** includes the one-command demo and the feature-explainer
skill. Existing `taskfilm run` workflows remain supported; see the
[one-run guide](AGENT-RUN.md).

## Try the tools first

Follow the [installation instructions](../README.md#install), including Chromium,
FFmpeg and Node.js 22+. Then run:

```bash
taskfilm doctor
taskfilm capture check
taskfilm demo my-first-film --render --quality draft
```

The original Taskboard sample starts locally, adds a task, completes it and
filters the result. The output includes `lesson.mp4`, `composition/`, the exact
recorded take, assertion screenshots and `DEMO-RESULT.json`. Watch the movie
before sharing it. This verifies the sample workflow; your own app needs its own
actions and result checks.

## Add the workflow to your agent

Install once into the skill folder your agent uses:

```bash
taskfilm skill ~/.codex/skills/taskfilm-feature-explainer --name taskfilm-feature-explainer
```

Existing destinations are refused. If your agent already has the skill, use that
installation or choose a new destination when upgrading; keep your own edits.

Start a feature task with this prompt, replacing the app and feature:

> Use $taskfilm-feature-explainer while building the Completed filter in my app.
> The app runs at http://localhost:3000. When the feature works and its checks
> pass, make a short walkthrough showing where to find it, how to use it and the
> result. Show progress and the preview here. Keep the original take and editable
> project so I can revise the explanation.

Give the agent the app's existing start command, a repeatable test state and a
concrete success condition. For this example: start with two tasks, complete one,
select Completed, and verify that only the finished task remains visible.
Use your own authorized data and account when the app needs them.

## Work and review in the same chat

1. **Build and check.** The agent implements the feature and verifies the useful
   task in the running app. A passing commit or unit test alone cannot prove the
   visible result.
2. **Record the stable version.** The agent records real actions and asserts the
   expected result. It retains the capture script, exact take and screenshot
   hashes. It does not film every edit.
3. **Explain the task.** Short captions identify the benefit, actions and result.
   Natural-speed interactions and a readable final hold make the lesson usable.
   Narration can use supplied audio; a silent captioned lesson needs no voice API.
4. **Review the movie.** The agent checks decoding and samples the actual encoded
   picture, then returns the movie and editable composition here. Watch the
   complete movie before sharing; listen too when it has audio.
5. **Revise or share.** Change copy or pacing using the valid take. A change to the
   demonstrated feature requires fresh checks and a new recording of that version.

Say **“stop filming”** to stop the demo while feature work continues,
**“continue filming”** to resume valid stages, or describe a feature/video change.
**“Stop everything”** stops both. These are instructions to the active agent.

If you want the agent to keep building while another agent films, add:

> Film this checked version in the background with one temporary helper, and
> return its progress and finished movie to this chat.

This is optional and depends on your agent's tools and repository rules. Keep the
captured target stable while the helper works. Installation does not add a Git
hook, an always-on watcher, chat buttons or a background render service. A worker
or render failure is retained as incomplete output with a specific blocker.

## Reuse the result

- **Feature handoff:** send the movie and a few usage steps to the person using
  the feature.
- **Release notes:** link the checked version and the task it demonstrates.
- **Product update:** make a tighter promo from the same real take using the
  [motion recipes](WORKFLOWS.md).
- **OSS walkthrough:** pair a real task with pinned source attribution using the
  [OSS recipes](../src/taskfilm/examples/oss-showcases/README.md).

Keep the film tied to the version it shows. The plan, successful capture,
verified app result and reviewed movie are separate stages. Publishing to a
repository or social account remains a separate action you authorize.
