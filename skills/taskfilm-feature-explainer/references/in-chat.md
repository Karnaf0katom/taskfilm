# Feature work and filming in one conversation

## Readiness and revision

The parent owns the feature request, the timing decision, user steering and final
delivery. Choose a cohesive milestone such as “create a task and filter completed
items,” rather than a list of every changed component. A task is ready to film
when these facts are available:

- The real app URL or executable and its existing start/build recipe.
- A repeatable starting state, actual actions and an observable success condition.
- Passing acceptance evidence for the behavior shown, including the real result
  in the running app for a browser feature. Test fixtures alone do not prove it.
- Stable labels, layout and test data for that task, and authorized local inputs.

Wait only for missing facts needed by this task. Continue implementation or checks
that can supply them. Preparation can happen earlier; recording starts after
readiness. Capture a baseline before an edit only when the user wants a before/after
comparison and the existing state can be verified.

Assign a revision to the task. Retain a fingerprint of the relevant working-file
contents and the running build/version, where available, alongside the acceptance
commands/results. HEAD alone misses uncommitted changes. Include copy and capture
inputs that affect the lesson. Use the project's existing artifact location and
a separate output directory per revision. Do not overwrite a take or movie.

Check the fingerprint before capture, after capture and before delivery. The
parent must know which build is running; a source hash cannot establish that a
hot-reloading app stayed unchanged. During capture, leave that target stable or
use an existing fixed preview that is already authorized. Other work can continue.
An affected source, build, URL, data or workflow change makes the earlier result
stale. Preserve it as an earlier version; recheck the feature and coalesce further
edits before one replacement recording. Unrelated edits do not require a new take.

## Optional background helper

Use this route when the user asks for background filming or has already authorized
it for this feature workflow. Skill installation and automatic skill selection
are not delegation authorization. Respect the current repository's helper rules.
When native background tools are available, use one short-lived worker rather
than another persistent conversation, CCC seat, ticket or watcher. In Codex use
`collaboration.spawn_agent` with `agent_type: worker` and `fork_turns: none`.
Do not inherit the full parent history or escalate to an expensive model for filming.
If delegation is unavailable, report that and perform the same stages in the
owning conversation. Do not fabricate a background job.

One worker mission has one deliverable, one acceptance check and a compact report.
For example, adapt this brief with actual paths and evidence before dispatch:

> Make one reviewed feature walkthrough for revision 2 of the checked Completed
> filter. Read the target repository's AGENTS.md, this skill and its production
> reference. The target URL, reset recipe, actions, passing checks and source/build
> fingerprint are in the attached feature record. Write only in the assigned
> revision output directory. Use the existing Taskfilm capture and render owners.
> Acceptance: execute the specified real task, verify its assertion screenshots,
> decode the movie and review the visible steps/result (plus complete audio if
> supplied). Report ready/blocked/stopped, revision, artifact paths, stage results,
> checks and the concrete blocker. Keep capture and edited-movie completion separate.
> Do not edit product source, commit, deploy, publish or spawn another helper.

The worker receives the smallest relevant context; point to local records rather
than copying the conversation. It cannot fix the app if capture fails: return the
failure to the parent. Existing compute gates and provider/account restrictions
apply. Paid narration or a new external destination needs its own authorization.

Keep the parent-owned request, revision, desired state and output folder in
`FEATURE-WALKTHROUGH.json`; add the helper id when dispatch returns it. The worker
writes phase, receipts and known process/execution handles to its own
`FILM-RESULT.json` at stage transitions. Check the parent's desired state and
revision before starting each new stage; never overwrite its stop/change request.
Use an atomic file replacement for each record update and omit secrets. The
parent can inspect these small artifacts without reading the worker's transcript.
Suggested phases are
`waiting`, `recording`, `composing`, `rendering`, `ready`, `stopped`, `stale`, `blocked`.
Retain capture verification, rendered, visual review and audio review as separate
fields. “Ready” requires the reviewed output, not just a successful capture.

The parent collects the worker's final report before ending the feature handoff,
checks the revision again, and inspects the result/movie before claiming delivery.
Delegation does not replace verification. Do not leave an uncollected job running
after reporting the feature finished. A renderer failure keeps the original take
and project available as partial results. After two attempts hit the same unchanged
blocker, park that stage with evidence and a concrete resume condition.

## Controls from this chat

Handle these as instructions, without asking the user to switch to another chat:

| User message | Parent action |
|---|---|
| Stop filming / pause the video | Mark the demo stopped, interrupt its helper and stop its known capture/render processes; continue already authorized feature work. |
| Stop / stop everything | Stop active work and filming. Resolve ambiguous scope before resuming anything. |
| Continue / continue filming | Resume the previously stopped scope; inspect partial files and the current fingerprint before resuming a demo stage. Keep a repeated blocker parked unless evidence changed. |
| Change the feature | Stop capture if the target will change, mark affected output stale, implement and recheck, then film the updated milestone. |
| Change the explanation, pacing or voice | Keep the valid take; revise the composition/audio and check the affected output. |
| Keep building; film later | Stop/defer the demo and retain its plan; continue the authorized build. Resume filming only when requested. |
| Film this version now | Check readiness; record the current revision and keep its target stable during capture. |

An agent interruption may leave a tool process running. Preserve known exec
session ids, process group ids or queued job ids and stop only this job's work
through the available lifecycle tool. Do not use broad `pkill`, stop a shared app
server or kill another seat's work. If cleanup is still pending, say so and avoid
launching a replacement. On cancellation, hold dependent stages and retain partial
files as incomplete. Do not start further paid stages or automatically restart.

## Show reviewable progress here

Use short updates at actual transitions, for example: “The filter is checked.
Recording this version in the background; next is the result review.” While work
is active, follow the conversation's update interval; no permanent polling loop.
Show a verified result screenshot or the original capture once available so the
user can steer before the edited movie is ready. Label the recording accurately.

When the movie passes review, show a playable attachment or preview if supported.
Otherwise link the exact local file and a readable result image. Do not imply
that every chat can play local MP4 files inline. Put the preview/artifacts,
acceptance result, current version and next authorized step in the same message.
Accept ordinary-language changes; do not invent slash commands or require buttons.

If the user asked to review before further changes, hold that dependent work.
Otherwise continue work they already requested; a preview is not a new approval
gate. Do not add features based on silence. Persist the stopped/stale/blocked
state and remaining work for a handoff so a resumed owner does not restart it.
