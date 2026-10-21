# OpenScreen comparison and Taskfilm additions

Reviewed 2026-10-14 against [OpenScreen's README](https://github.com/getopenscreen/openscreen)
and [roadmap](https://github.com/getopenscreen/openscreen/blob/main/ROADMAP.md).
The repository HEAD observed during review was
`b668b2c8da908fefef4cf0fec73c32282d0b1243`. Its roadmap identifies a separate
review date, so planned features are not treated as implemented features.

Taskfilm's existing owners already provide browser workflow capture, action
and screenshot evidence, click-driven zoom planning, dead-air removal,
captioned lessons, landscape/portrait composition, motion graphics and a CLI.

| Capability | Taskfilm status after this addition |
| --- | --- |
| Import an existing screen recording | `polish` retains the original and authors an editable composition |
| Reusable backgrounds, padding, rounding and shadows | Three original presets and a shareable JSON style |
| Trim, cut and per-range speed edits | Source-time edit contract; audio follows the edit with pitch-preserving speed changes |
| Manual zoom depth, duration, position and easing | JSON zoom ranges; existing compositor spends the edit |
| Automatic zoom | Existing click-cluster planner reused for supplied timed clicks |
| Cursor styling, smoothing and click effects | Optional original pointer, idle hiding, smoothing and click rings from supplied samples |
| Text annotations | Plain text labels tied to source-screen coordinates and edit timing |
| MP4 and GIF delivery | Existing HyperFrames movie render and new palette-optimized GIF command |
| Full desktop/window capture, microphone, system audio and webcam | Not added to the public CLI; capture remains the existing browser workflow |
| Offline speech transcription and transcript-driven editing | Not included; existing supplied captions/voice remain available |
| Desktop timeline, keyboard shortcut editor and AI chat editor | Not included; FreeCut remains the repository's human-editing owner |
| Blur/redaction, webcam processing and native GPU export | Not implemented by this addition |
| macOS and Windows installers and platform verification | Not provided; the current distribution remains a Linux-checked Python alpha |

The additions are original Taskfilm code under the project's MIT licence.
No OpenScreen code, assets, styles, brand material or dependencies are copied
or bundled. OpenScreen is a capability reference. Its own project retains its
[MIT licence and attribution](https://github.com/getopenscreen/openscreen/blob/main/LICENSE).

The publishable closure includes the new capture-owner modules, example edit
file, public documentation and installed-distribution acceptance tests. The
exporter binds them to SHA-256 values in `SOURCE-MANIFEST.json`. Publication
still follows the reviewed release workflow in [RELEASE.md](../RELEASE.md).
