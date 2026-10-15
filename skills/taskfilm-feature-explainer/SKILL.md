---
name: taskfilm-feature-explainer
description: Work on UI or features with Taskfilm walkthroughs at checked milestones, optional background filming, and progress, previews and stop/change controls in the same chat. Use when the user wants to see and steer working changes through a demo during implementation or at handoff.
---

Turn a checked feature into a lesson the user can follow: what changed, why it
helps, how to use it, and the visible result. Load this skill at the start of a
feature request when the user wants demos as they work, or after a finished change.
Keep the implementation, filming and review in the owning conversation. Group
related changes into one useful task; follow the user's language and delivery format.

Use the installed Taskfilm CLI and its existing capture, story, composition and
render owners. Read [the production reference](references/workflow.md) when
making the film. Read [the in-chat workflow](references/in-chat.md) for readiness,
background delegation, revision handling and user controls.

## Choose the filming moment

Carry the user's request for walkthroughs through the current feature task. At a
meaningful milestone, check whether one useful user task works in the actual app,
its relevant acceptance checks pass, and the controls and data to be filmed are
stable. A commit alone does not establish readiness; uncommitted checked work can
be ready. A missing app or failing task stays in implementation with a specific
reason. Do not film every edit or wait for unrelated backlog to finish.

Once the milestone is ready, start the already requested walkthrough without
another confirmation. If the user requested background filming, use at most one
temporary helper through the current harness when available and authorized.
Give it only the checked task, target, acceptance evidence, current revision and
an owned output folder. It films; the parent continues work that will not change
the captured target. Otherwise make the walkthrough in this conversation.

Report readiness and capture/render progress here. Show the verified task result
as soon as it is available, then the reviewed movie. Attach a playable file or
preview when the chat supports it; otherwise give a direct artifact link and a
readable result screenshot. Keep one owner and return the helper's result here.

## Keep the walkthrough steerable

Treat new messages as steering for the active feature and demo. “Stop filming”
stops the demo; “stop everything” stops both. “Continue filming” resumes from the
last valid stage. A requested feature change returns to implementation and new
checks before recording the changed behavior. A copy, pacing or narration change
can reuse a still-valid capture. Plain “stop” stops active work first; clarify
scope only if needed before resuming. Never interpret silence as permission to
resume a stopped task.

Retain takes and track which feature revision each shows. If edits affect the
captured task, invalidate the old result and stop the helper before starting a
replacement. Show old versions only with their version clearly identified.
Report what is checked, what the user can review, and the next authorized step
so they can decide to stop, continue or change direction in this chat.

## Ground the lesson in the finished change

Inspect the actual diff, current product and acceptance results. Choose one task
that becomes possible or easier because of the change. Write down its starting
state, actions and success condition. Distinguish a checked local feature from
a deployed feature. For an existing feature walkthrough, describe its present
behavior without inventing a recent upgrade.

Explain the user benefit in one sentence, then plan a compact sequence:

- What changed and the situation where it helps.
- Where to find it and any prerequisite the user needs.
- The actual actions, with short instructions beside the real product.
- The verified result, held long enough to read.
- A specific task the viewer can try next.

A 30–60 second lesson is a useful default, not a fixed template. Show the
workflow at natural speed; remove idle setup without hiding required actions.
Use the changed product's own labels, data and appearance. Keep motion modest
enough to leave the controls and result readable.

## Make and check the walkthrough

For a browser feature, record the running product and assert the expected result.
For a CLI or backend feature, execute the real commands and retain their output;
present verified excerpts or a diagram when there is no meaningful screen task.
Label diagrams as explanation. Source excerpts establish what the code says;
only executed checks establish runtime behavior.

Author the copy and choreography for this change. Taskfilm's story command
produces a plan; the composition command does not automatically execute that
plan. Apply the explanation to the beat labels or editable composition and
review it. Use supplied narration when available, or a captioned silent lesson.
Voice generation is a separate step using the user's authorized provider.

Inspect the real result, the rendered controls and text, the opening, every
action, and the final hold. Check timing and decoding. If audio is supplied,
listen to the complete encoded track. Correct an observed problem, then repeat
the affected check. An unavailable app or failed check is a concrete blocker;
retain the partial files and report the missing input without declaring a film
finished.

## Finish the feature handoff

Deliver the movie, editable project, a few written usage steps and the check
that confirmed the result. State any prerequisite or product limitation needed
to use the feature. Record which capture, render and review steps actually
finished. Link the walkthrough in the final feature response and include the
current revision and any remaining work so the user can steer the next change.

Keep local artifacts local unless the user authorized a sharing destination.
This skill runs within an active agent conversation. Installation makes it
discoverable; it does not create an always-on watcher, Git hook or render service.
