# Feature work and filming in one conversation

## Readiness and revision

The parent owns implementation, user steering and final delivery. Film a cohesive
checked task, not every edit. Retain the actual target URL/executable, reset
recipe, user actions, observable result, passing backend/UI acceptance evidence,
and relevant working-source and running-build identities. HEAD alone misses
uncommitted changes; source hashes alone cannot prove which build a URL serves.
Keep that target stable during recording. Continue only work independent of it.

Use a separate owned output folder per revision. `taskfilm run` hashes its script
and repeated `--source` files at stage boundaries; a change stops the run as stale.
Record other build/data changes yourself and invalidate affected footage. An
unchanged take can support new copy or pacing; a changed feature needs fresh
acceptance evidence and capture. Keep older versions clearly identified.

## One optional worker

Use a helper only when the user authorized background filming and useful
independent work remains. Installation and automatic skill selection do not
authorize delegation. Respect repository and harness rules. In Codex use one
temporary `agent_type: worker`, `fork_turns: none`; no full-history fork,
expensive model escalation, persistent seat, watcher, ticket or grandchildren.
If unavailable or unhelpful, execute the same workflow in the owning conversation.

Give the worker paths and facts, not the transcript. One bounded mission:

> Deliver one reviewed feature walkthrough for REVISION. Read the repository's
> AGENTS.md and this skill. TARGET and reset/actions/result are in FEATURE-RECORD;
> its backend/UI acceptance checks passed. The capture script and relevant
> source/build identity are there. Write only to OUTPUT. Run `taskfilm run` for
> the specified treatment; use the exact verified take only when its revision
> matches. Inspect its result image and full-size movie frames, verify caption
> playback, and review complete supplied audio. Acceptance: the actual task and
> reviewed movie match REVISION. Return only final status, revision, artifact
> paths, check/review results and concrete blocker. No product-source edits,
> publishing, new provider calls, commits or helper delegation.

The parent retains revision, desired state, output path and helper id in its
existing feature record, plus known harness execution/session handles needed
for cancellation. The CLI's small atomic `run.json` already records phase,
receipts, logs and artifact paths; inspect that instead of polling a transcript
or duplicating phase records. The worker can leave its final visual/audio review
and blocker in `FILM-RESULT.json`; a `rendered` CLI status alone is not review.

Collect the worker before ending the feature response and recheck the revision.
Do not report delivery while an uncollected render is still running. After two
attempts hit the same unchanged blocker, retain partial files and name the
condition needed to resume. A copy/pacing revision can reuse a valid take.

## Controls from the same chat

| User instruction | Parent action |
|---|---|
| Stop filming / pause the video | Mark the film stopped and interrupt its known worker/command; continue authorized feature work. |
| Stop / stop everything | Stop active implementation and filming; resolve scope before resuming. |
| Continue filming | Recheck partial files and revision, then explicitly resume the stopped film. |
| Change the feature | Stop affected filming, implement and check the change, then capture a new revision. |
| Change copy, pacing or voice | Reuse a valid take and check the revised composition/audio. |
| Keep building; film later | Stop/defer filming and continue the authorized feature work; do not auto-restart filming. |
| Film this version now | Check readiness and keep its target stable during capture. |

Use the current harness lifecycle tool or a known process handle for this job.
The CLI handles SIGINT/SIGTERM and command deadlines, terminating its child
process group on POSIX and retaining partial artifacts. Never use broad `pkill`
or stop the shared app server. An uncatchable kill can leave a lock/process;
confirm cleanup before a replacement. Silence never resumes a stopped job.

## Progress and final handoff

Report meaningful transitions here without a permanent polling loop. Show the
checked result as soon as available, then the reviewed movie. User requests
steer both feature and film in this conversation; a preview is not an extra
approval gate unless they requested one.

Use a playable attachment when the client supports it. Otherwise provide the
exact local MP4/preview links and a readable result image. Include backend/UI
acceptance results, filmed revision, minimal usage steps and any remaining
work in that same final response. Do not promise inline MP4 playback in every
client. Files stay local unless a sharing destination was authorized.
