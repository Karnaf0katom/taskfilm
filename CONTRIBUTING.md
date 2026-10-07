# Contributing

Use Python 3.10+; install `.[browser,motion,dev]` in a virtual environment. Run
`python -m pytest -q` before proposing a change. Browser verification uses the
original local Taskboard sample and a fresh browser context. It needs FFmpeg
and Chromium; unit tests need no signed-in browser or provider account.

Preserve the separation between story planning, capture, edit decisions and
rendering. Put behaviour with its existing owner; the CLI dispatches to those
owners. In the source monorepo, the release exporter copies an exact allowlist
and hashes it. Update that inventory when a supported command adds a runtime
dependency. Confirm both the wheel and source distribution contain the files.
CI installs and tests both built distributions from outside the checkout.
The opt-in browser integration check allows five minutes per recording,
including FFmpeg encoding; `TASKFILM_CAPTURE_TEST_TIMEOUT` overrides that limit
in seconds. Successful actions, retained results and screenshot hashes remain
required even on a busy CPU host.

Keep output honest: a prepared plan is not proof of execution, and a capture
assertion is not a human review. Keep real task actions readable. Review final
frames at delivery size and listen to complete narration when supplied.

Use original or explicitly licensed fixtures. Keep third-party notices with
fonts and reference material. Never add real account states, credentials,
client media, database dumps or generated recordings to the repository.
