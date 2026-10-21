# Polish a screen recording

Import your existing recording into an editable Taskfilm project. FFmpeg and
FFprobe are required. This works without Playwright, an account or an AI provider.

```bash
taskfilm polish recording.mp4 my-screencast --preset paper
taskfilm render my-screencast --output screencast.mp4
taskfilm gif screencast.mp4 --output preview.gif --width 960 --fps 15
```

`polish` authors the composition and encodes its edited source. `render` makes
the final movie through the existing pinned HyperFrames runtime. Preview with
`cd my-screencast && npm run dev`. The destination must be new; existing projects
and GIFs are never overwritten. Rendering needs Node.js 22+ and npm and may
download the pinned runtime and GSAP.

The project keeps the exact original recording in `original/`, edited footage
and retained audio in `assets/`, editable `index.html`, reusable `edits.json`,
and a source hash and edit receipt in `POLISH.json`. Original audio is retained
by default, including pitch-preserving speed changes. The edited working clip
uses 30 fps; the original stays byte-for-byte unchanged. Use `"audio": "mute"`
to author a silent project. GIFs always omit audio.

## Reuse your style and edits

`studio`, `paper` and `midnight` supply original backgrounds, rounded corners,
padding, shadows and accent colours. The screen fits inside the frame without
cropping the source UI, including landscape footage in a portrait canvas.

```bash
taskfilm init sample
taskfilm polish recording.mp4 custom-film --spec sample/screencast.json
taskfilm polish custom-film/original/recording.mp4 revision --spec custom-film/edits.json
taskfilm polish recording.mp4 portrait --width 1080 --height 1920
```

Edit `edits.json` and rebuild into a new directory. The dimensions and resolved
style are saved with the edit, so moving the project does not depend on the
original recording path. Explicit dimension and preset flags take precedence
over their spec fields; `style` overrides the selected preset's defaults.

## Source-time edit contract

All times are seconds in the **original recording**, before any cuts or speed
changes. Positions are normalized from 0 to 1, with `(0, 0)` at the screen's
top left. Zooms, labels, clicks and cursor samples follow the edited clock;
events inside removed footage disappear. Adjacent kept sections do not blend
cursor movement across the removed action.

For a recording at least eight seconds long:

```json
{
  "schema": "taskfilm-polish/v1",
  "preset": "midnight",
  "style": {"background": ["#142124", "#080e10"], "padding": 64},
  "trim": {"start": 0.5, "end": 8},
  "cuts": [{"start": 3, "end": 4}],
  "speed": [{"start": 4, "end": 6, "rate": 2}],
  "zooms": [{"start": 1, "end": 2.5, "x": 0.7, "y": 0.4, "scale": 1.6, "ease": "smooth"}],
  "annotations": [{"start": 1, "end": 2.5, "x": 0.5, "y": 0.8, "text": "Choose a template"}],
  "cursor_overlay": false,
  "cursor": [{"t": 1.5, "x": 0.7, "y": 0.4, "click": true}]
}
```

`trim` chooses the retained outer range. `cuts` removes ranges within it.
`speed` supports rates from 0.25 to 8; cut and speed boundaries split the
footage into explicit retained segments. Ranges in each of `cuts`, `speed`
and `zooms` must not overlap. An edit that removes everything is refused.

`zooms` supports scales from 1 to 3 and `gentle`, `smooth` or `linear` easing.
`annotations` holds escaped plain text, positioned in screen coordinates.
`style.background` takes one `#RRGGBB` colour or a two-colour gradient; `angle`,
`padding`, `radius`, `shadow`, `accent` and `cursor_size` are also editable.
Unknown fields and nonfinite or out-of-range values are rejected before import.

## Cursor samples and automatic focus

Supply strictly increasing `cursor` samples with `t`, `x`, `y` and optional
`click`. Clicks draw expanding rings even with the pointer overlay disabled.
Set `cursor_overlay` to true to draw an original Taskfilm pointer. It hides
after 1.5 seconds without samples. `cursor_smoothing` is a time constant from
0 to 0.5 seconds; clicks use the exact recorded position.

Set `auto_zoom` to true to use the existing click-cluster planner. Explicit
manual zooms take priority over automatic ranges that overlap them. No cursor
tracking is inferred from the pixels. A pointer already burned into a recording
cannot be removed; leave the overlay disabled for that footage.

## GIF excerpt

```bash
taskfilm gif screencast.mp4 --output payoff.gif --start 5 --duration 4 --width 640 --fps 12
```

This uses a generated palette, bounded frame rate and an endlessly looping
GIF. A failed encode leaves no partial destination file.

Review the final video before sharing. Importing a clip does not verify its
workflow, transcribe speech or redact sensitive screen content. The receipt
reports those verification limits explicitly.
