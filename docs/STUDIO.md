# Visual studio and complete versions

Taskfilm Studio shows Brief → Capture → Storyboard → Audio → Composition → Render → Publish. Each save, restored version and completed stage creates a complete directory. It includes the real capture, brand assets and licenses, editable scene and audio JSON, available HTML composition, narration clips, music, captions, previous renders and a SHA-256 manifest. A stale preview remains available while you make changes.

Start with a **Projects library** to browse and open multiple films from one home page:

```bash
taskfilm studio register ./project-library ./studio-workspace --id my-product --default
taskfilm studio serve ./project-library --library
```

The home page shows thumbnails, names, portrait/landscape format, duration, current-version size, version count and last-edited date. Search, filter by format, and switch between grid and list views. Click a project to open its own stage editor at `/projects/<id>/`; **Projects** returns to the library. Each project has separate files, HEAD, versions, jobs and downloads. Existing workspaces are registered by reference without moving or changing their history. The registry lives in `project-library/library.json`; new projects live in `project-library/projects/<id>/`.

**New project** creates an editable draft with three starter scenes. **Duplicate** copies the latest complete version into an independent project with its own history. It preserves source media and saved outputs; later edits never change the original. Creating, browsing and duplicating projects does not generate narration or send posts. New drafts start without a product capture; add real captured footage through a workspace import before making a product demonstration.

`taskfilm studio list ./project-library` lists registered projects. Serving a single workspace without `--library` still opens its editor directly. In library mode, legacy root `/api/state` and `/files/…` links refer to the default project; every editor and its export/media links use the project-specific route.

Existing `product-motion/v1` films can be imported with their original capture and edit decisions:

```bash
taskfilm studio import-legacy ./project-library/projects/reports-portrait \
  --spec ./reports/spec.json --format portrait --movie ./reports-portrait.mp4
taskfilm studio register ./project-library ./project-library/projects/reports-portrait --id reports-portrait
```

The importer preserves the finished movie byte for byte, native HTML, fonts, licenses, music and capture evidence in one complete version. It also creates editable scenes from the original timings. Imported projects display a notice: their initial preview is the original film; rebuilding after scene edits uses Studio's current layouts. Their original visual render is never treated as a cache of the newer composition. Native HTML retains its existing GSAP CDN dependency. The supplied spec must have its original take and `cuts/<format>/` assets available; import does not record a new take, generate speech or post anything.

Import a film into a **new** workspace:

```bash
taskfilm studio import ./studio-workspace --ad ./ad.json --audio ./audio.json \
  --composition ./editable-project --raw-video ./uncaptioned.mp4 \
  --delivery ./finished.mp4 --capture-dir ./original-take \
  --name 'My product campaign' --narration-host my-mac --voice 'Zoe (Premium)'
taskfilm studio serve ./studio-workspace
```

Only `--ad` is required. Other arguments preserve existing outputs and evidence. In Audio, choose Google, macOS, Deepgram or ElevenLabs, a voice and speaking speed. Google uses Gemini 2.5 Flash TTS directly from the server; supply `GOOGLE_API_KEY` or `GEMINI_API_KEY` in its environment before starting Studio. Kore is the default Google voice; Aoede and Zephyr are alternatives. Account quota and pricing apply. Keys stay outside full project versions. If a key already lives in an env file on another machine, set `TASKFILM_GOOGLE_KEY_REF=host:/absolute/env/file#VARIABLE` on the server. It reads the key once per server process over SSH; speech generation runs on this server. A server restart needs that credential host reachable. macOS uses `say`; on Linux it needs an accessible Mac SSH host. Deepgram and ElevenLabs use the optional `video-claw` adapter and its credential lookup. The server defaults to `http://127.0.0.1:8795/`. Use `--host` to expose it on a trusted network when needed.

If HyperFrames cannot download its browser, set `HYPERFRAMES_BROWSER_PATH` to an installed Chrome/Chromium binary before starting the studio. The Render stage uses the `looks` quality preset.

Open a stage, edit a scene or narration line, then save a named version. The stage rail shows which later work needs updating. Run affected stages in order. Completed jobs save another full version; edits made during a running job are kept, and its result remains separately available in Versions.

In **Storyboard**, select a scene and choose its **Layout** from eight built-in scene templates: Hero stage, Editorial split, Proof strip, Detail poster, Quiet card, Caption rail, Type led and Brand close. Save, build Composition and Render to see layout edits in the movie. These are scene layouts, rather than a gallery of complete video presets.

The saved video and Storyboard scene selector sync in both directions. Playback and scrubbing highlight the current scene; clicking a scene seeks straight to its start, preserving whether the preview is playing or paused. Scene navigation retains unsaved edits. Timing follows the saved movie, including earlier renders and historical versions; changing draft durations does not move boundaries in an older preview. New saved versions retain a movie hash and scene boundaries in `delivery.timeline.json` so exported and duplicated projects keep the same mapping. Projects without a render still allow scene editing.

| Change | Reused | Update |
| --- | --- | --- |
| Headline, body, crop or layout | Capture, music and narration | Composition, then Render |
| Voice provider, voice name or speed | Capture and visual render | Audio, then Render |
| One narration line | Capture, unchanged narration lines, visual render | Audio, then Render |
| Music volume or narration timing | Capture, narration files, visual render | Audio, then Render |
| Scene duration | Capture and existing voice files | Audio, Composition, Render; narration must still fit |
| Publishing title or caption | Entire finished film | Publish preparation |

Composition contains visuals only. Render reuses the existing uncaptioned visual MP4 whenever scene inputs are unchanged, then adds the new mix and captions. Updating a scene rerenders the composition; per-scene rendering is not yet supported. Capture verifies imported source files; new browser recording uses `taskfilm capture` and a new workspace import.

Versions can be inspected, restored and downloaded as complete ZIP files. Restoring never overwrites the original. Each is an ordinary directory in `workspace/versions/<id>/`. Working files reference local assets using relative paths. `VERSION.json` lists files and hashes; exports verify these before download. Work on a copy when editing outside the studio: modified sealed versions are rejected to protect their history.

```bash
taskfilm studio export ./studio-workspace --version <id>
# Reopen an extracted bundle in a fresh workspace:
taskfilm studio import ./continued --ad ./extracted/ad.json --audio ./extracted/audio.json \
  --composition ./extracted/composition --raw-video ./extracted/raw.mp4 \
  --delivery ./extracted/delivery.mp4
```

The imported campaign defaults to English and Instagram, Facebook and YouTube. Publish prepares a release file with the video hash, metadata and music credits. **It does not send live posts.** Account reconnection and the YouTube channel choice remain necessary for the existing publishing worker. Credentials are excluded from studio versions.

The player places controls outside the video to avoid covering captions or the call to action. HTTP byte ranges allow seeking without downloading the entire film first.
