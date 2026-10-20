# Revit course handoff

[Download the Windows starter ZIP](https://github.com/Karnaf0katom/taskfilm/releases/download/v0.1.0a4/Taskfilm-Revit-Starter.zip) ·
[הוראות התחלה בעברית](../examples/revit-course/START-HERE.he.txt) ·
[Browse the companion source](../examples/revit-course/)

This Windows starter helps a nontechnical Hebrew-speaking instructor prepare
short classroom demonstrations, retain feedback and add Hebrew narration.
It is a separate, explicitly assembled handoff alongside the published Taskfilm
0.1.0a4 wheel; the companion files are separate from the installed Python package.

## Start on the Windows PC

1. Extract the ZIP into a local folder on the PC with Revit installed.
2. Double-click `00-SETUP.cmd` to install the recording dependencies and published Taskfilm wheel.
3. Follow `START-HERE.he.txt` to connect OBS, then double-click `01-START.cmd`.
4. Record and watch a ten-second test before preparing the first lesson.

The same starter source lives in `examples/revit-course/`. Its `.env.example`
contains blank credentials. Supply a voice key privately in `.env` on the
recipient's PC; a key is needed only for AI narration. Recording works without it.

The output contains a credential-free ZIP, Hebrew start guide, double-click
Windows setup/menu, lesson templates, a course outline and a prompt for a local
AI assistant. The installer verifies the published Taskfilm 0.1.0a4 wheel's hash.
The adapter reuses capture-lane's OBS recorder, humanflow's native input owner
and edit-lane's TTS registry. It never exports the shared checkout or key pools.

Supply a single selected voice key separately as `.env`; recording needs no
AI API key. The Hebrew model is explicitly `eleven_v3`, because the existing
Multilingual v2 default does not cover Hebrew. The AI assistant's own login is
separate. API allowance is shared with the selected account and is not unlimited.
Use a stock voice and an appropriate paid subscription for saleable narration;
the free plan does not provide commercial rights. See the provider's
[model documentation](https://elevenlabs.io/docs/overview/models) and
[publishing terms](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform).

The starter can record a teacher's demonstration and replay a compatible input
trace through humanflow. Replay checks screen dimensions and Revit focus, and
supports Escape to stop. A replay does not record a fresh take or prove the
resulting Revit model correct. It requires the same initial document/view,
resolution, scaling and interface. New autonomous Revit tasks need a locally
connected controller and independent result checks; the browser capture demo
does not establish this capability.

The MP4 delivery preserves demonstration speed and the full frame. Optional
narration begins at zero; the teacher must review its alignment with actions.
The source take, input trace, voice reads and delivery receipts stay local.
No course films, practice project, license purchase, AI subscription, public
publication or installation on the recipient's PC is implied by preparation.

Acceptance on her Windows/Revit PC: install; confirm the OBS preview shows the
entire primary Revit screen; record and watch a ten-second test; record one
30–90 second lesson; listen to its Hebrew read; review the exported MP4; reset
the practice file and test replay plus Escape/focus-loss stopping. Only then
call the Windows flow verified. Linux tests cannot close that gate.
