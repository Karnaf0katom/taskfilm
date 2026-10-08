# Preview the films and choose your option

[Open the video gallery](https://karnaf0katom.github.io/taskfilm/).
Use its filters to compare product films, feature lessons and motion graphics.
Every player contains a finished MP4. The editable-project downloads include
the actual source take and native results, where the film uses a browser task.

| Preview | What to watch for | Production option |
| --- | --- | --- |
| Excalidraw motion promo | Masked titles, a perspective browser reveal, the real draw/connect/save task, animated native diagram and a voiced end card | After Effects-style HTML/SVG product film |
| Excalidraw original promo · 45s | The native diagram, complete task, perspective entrance and readable result hold | Product promo |
| drawDB narrated lesson · 72s | Two real tables, a foreign key and the retained PostgreSQL SQL export | Recorded feature lesson |
| Taskboard product film · 31s | Camera moves, a click on the beat, result lift, recap cards and a scored end card | Directed product-film kit |
| Motion lab · 24s | Masked kinetic type, SVG path drawing, shape interpolation and perspective cards | Motion graphics without a screen recording |

The original Excalidraw, drawDB, Taskboard and motion-lab recordings retain the
earlier Jarvis wordmark. The narrated Excalidraw motion promo uses Taskfilm.
The motion lab deliberately uses silence; it does not demonstrate a missing
audio track. Penpot has a prepared recipe but no verified public film or native
export in this release.

## Pick the workflow

| You want to… | Use… | Editable output |
| --- | --- | --- |
| Teach one useful action | `capture` → `edit` → `compose` | Footage, beat labels and an HTML composition |
| Promote an app with a real payoff | `motion` or the Excalidraw motion-promo recipe | Directed HTML film, camera/recap decisions and source assets |
| Animate type, vectors and depth | `demo/motion-lab` | Four HTML/SVG scenes and seekable GSAP timelines |
| Review an open-source tool | `repo-pack` → `story` using the `github_review` story mode, plus a real capture | Pinned attribution, runtime evidence and a walkthrough composition |
| Make a vertical social cut | `reel` or `motion --format portrait` | A 9:16 HTML composition |
| Add ElevenLabs narration | Generate audio on your account, then supply it to the narrated recipe | Local narration clips and measured timing |
| Change the music | Supply a licensed WAV to the product-film kit or an audio file to the motion-promo recipe | Local score and editable audio placement |

The story mode is selected by the story JSON; see the [actual commands](WORKFLOWS.md).
After Effects-style describes the animation treatment. Taskfilm renders
HTML/SVG with HyperFrames; native Adobe `.aep` import and export are not included.

## Preview in the editor or download the movie

Use the gallery's MP4 players for the finished result. For an editable project,
download its archive, extract it, and run the project's pinned command:

The narrated Excalidraw project's download includes its visual assets and
narration. Supply your own licensed 48-second score at `assets/music.wav` before
rendering. The published score is included in the finished movie.

```bash
npm run check
npx --yes hyperframes@0.8.134 preview --background
npm run render -- --output your-film.mp4
```

For the included samples, run `taskfilm init demo` and follow
[WORKFLOWS.md](WORKFLOWS.md). Capture a new app with its own script and retained
result checks; a promo template does not establish that another app worked.

## Narration and score for the showcase

The new Excalidraw film uses the ElevenLabs George narrator and an original
instrumental electronic score, generated on an active paid account. Its six
measured narration cues leave room for drawing, connecting and saving. The
music receives a voiceover carve before the complete HyperFrames render.

Original code is MIT licensed. Generated audio has separate provider terms,
recorded in the film's media provenance; it is not covered by the code license.
Use your own provider account and licensed media when creating another film.
