# Original motion with variety

Taskfilm can author three different animation treatments from text, in landscape
or portrait, with editable HTML/Canvas sources and an original synthesized score.
Playback and encoding use the same pinned HyperFrames renderer as product films.
These are original motion graphics; use the capture workflow for proof of an app's behavior.

```bash
taskfilm treatments --brief "A bold headline for our launch" --seed 41
taskfilm animate my-film --treatment type-sculpture --headline "Make it move."
taskfilm render my-film --output my-film.mp4
```

Install the `motion` extra for audio: `pip install 'taskfilm[motion]'`.
Use `--silent` for a deliberately silent study. No model, paid API or account is required.

| Treatment | What changes in the picture |
|---|---|
| `type-sculpture` | Whole words land through masks, become a rotating extruded-looking word, and carry a wipe into a new statement. |
| `orbit-story` | One illuminated sphere leads a perspective journey through a gathering orbital system. |
| `signal-field` | Travelling ribbons become a rotating line sculpture, then resolve into a message. |

Orbit and sculpture use perspective-projected Canvas geometry; they do not claim
WebGL or a native 3D export. The original silent `motion-lab` remains available.

Generate a reel showing all three families or a separate portrait layout:

```bash
taskfilm animate variety --showreel --headline "Make it move."
taskfilm animate portrait --showreel --format portrait
taskfilm render variety --output variety.mp4
taskfilm render portrait --output portrait.mp4
```

The individual films run 12 seconds; the showreel runs 18. The final signature
holds for one second. Edit the embedded config in `index.html` for copy/palette
and `runtime.js` for the artwork. `ANIMATION-PLAN.json` records the authored
inputs; changing that record alone does not change rendered pixels.
Serve the project over HTTP and open `index.html?preview=1` for play/pause and a
seek slider. Preview controls are outside the film and absent from encoded frames.

## Avoid repeating a treatment

Selection compares the story device, opening, camera, transitions, layout,
sound pacing and ending. It preserves supplied brand colors. `--seed` makes
ties reproducible; changing a seed alone does not establish a different film.
Supply a caller-owned history to both commands:

```bash
taskfilm treatments --brief "Our next motion study" --history history.json
taskfilm animate next-film --brief "Our next motion study" --history history.json
```

The history schema is `taskfilm-treatment-history/v1` with an `events` array.
After reviewing a finished encoded film, use `taskfilm record-review PROJECT
--movie FILM.mp4 --history history.json --reviewer "Your name" --confirm-reviewed`.
It records `status: reviewed`, the treatment and fingerprint, and the actual
movie hash. This is your explicit declaration, not an automated visual review.
See [the history guide](REVIEW-HISTORY.md) for validation and limitations.
Planned and failed events do not consume variety; two formats
of one structure count once. The last five distinct reviewed structures are
considered. Exhaustion is explicit; `--allow-repeat` permits intentional series
reuse. Neither planning nor authoring writes to history automatically.

Use `--brand-file demo/brand.json` to apply reusable copy and palette values;
explicit flags override the file. `taskfilm init demo` includes an original
example. The [brand-file guide](BRAND-KIT.md) describes its schema and provenance.

## Finish and review

1. Choose a short headline that belongs to the subject and a suitable treatment.
2. Author with your brand, tagline, format and supplied palette. Use `--help` for flags.
3. Scrub the source in both directions; a repeated time must produce the same image.
4. Render through `taskfilm render`, then inspect encoded opening, transitions,
   hero moments and close. Check full decode, dimensions, FPS, duration and audio.
5. Inspect readable text at delivery size and listen to the whole score before sharing.
   Record the actual checks in the generated `NOTE.md`; authoring alone is not a review.
6. Package the reviewed film through `taskfilm package` with its hash and editable project.

The animation renderer is a pure function of absolute time. It uses moving entries,
directional cuts, material lighting and a short resolved close. A moving image and
passing technical checks still need visual judgment.

## Credit and scope

Craft research includes [Motionmaxxing by Tejas Makwana](https://github.com/Tejashmakwana/motionmaxxing),
pinned to `8c8ec0f2a6f6c9a0da15cd24f7b1298ab298368c`. We adapted its emphasis on
story-driven movement and rendered-frame review into our existing owners.
These recipes and artwork are original Taskfilm code; no upstream films,
brand assets, runtime, fonts or skill installation are copied.
Manrope retains its bundled OFL notice; GSAP and HyperFrames retain their own terms.

The repertoire currently has three authored families. It is not a port of every
technique in a reference library. The selector is usable by the private Director
and the public CLI; automatic private-run history synchronization is separate.
