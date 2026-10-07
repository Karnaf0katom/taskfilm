# Taskfilm releases

The first public version is **0.1.0a1**, an alpha for Linux, Python 3.10+ and
Chromium. Original code is MIT licensed. Install from the standalone repository
or its GitHub release wheel; PyPI publication is not configured.

## Install a release wheel

Download the wheel and `SHA256SUMS` from
[GitHub Releases](https://github.com/Karnaf0katom/taskfilm/releases), then verify
the wheel against its named checksum before installing it.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install './taskfilm-0.1.0a1-py3-none-any.whl[browser,motion]'
python -m playwright install chromium
taskfilm doctor
taskfilm capture check
taskfilm init demo
```

FFmpeg/FFprobe and Node.js 22+ are installed separately.

## Maintainer publication

1. Review `LICENSE`, package metadata, third-party notices and `SOURCE-MANIFEST.json`.
2. Run CI against the wheel and source distribution, including real browser capture and the complete-render audio check.
3. Tag the reviewed commit `v` followed by its package version, such as `v0.1.0a1`.
4. The release workflow repeats CI and creates a draft prerelease with the wheel, source distribution and `SHA256SUMS`.
5. Add checked demo assets with their exact SHA-256 values, review the draft, then publish it.

Release workflows never upload to PyPI. The draft step lets maintainers check
the assets and notes before making a release public.

## Checked static demo

Attach `taskfilm-preview-v0.1.0a1.zip` and `DEMO-SHA256SUMS` to the matching
release. The archive must contain a nonempty `index.html` and relative local
assets at its root or inside one common wrapper directory. Use GitHub Actions
as the Pages source, then run **Deploy verified release preview** with that tag.

The workflow checks the exact archive checksum, rejects escaping paths,
duplicates, symlinks and oversized bundles, then deploys the retained site.
It never renders new movies during deployment.

The optional **Build from assets** input prepares the preview on the GitHub
runner from a checksum-bound `showcase.json`, release distributions, movies,
posters and historical editable-demo archive. It preserves original take and
composition bytes, adds current recipes and notices, attaches the resulting
downloads, and checks desktop/mobile playback before deploying. Historical
inputs are removed from the draft release after their public archive is ready.

The showcase includes checked 45-second Excalidraw and 72-second drawDB films,
plus an original 24-second motion study. Those recordings retain the wordmark
used before the public rename. Penpot remains a prepared recipe; a completed
Penpot film or native export is not included or claimed.

## Verification boundaries

The original Taskboard sample runs without accounts, API keys or a model.
Captures retain successful task assertions and hashed screenshots. The CLI
pins HyperFrames **0.8.134**. CI checks encoded loudness, peak, duration, frame
count and full decode through a normal complete render.

The earlier complete 31-second product-film check measured source
**−16.02 LUFS / −1.46 dBTP** and encoded **−16.08 LUFS / −1.39 dBTP**, without
separate audio assembly. These Linux/Chromium measurements do not establish
subjective audio review, portrait encoding, macOS or Windows support.

The source manifest binds each shipped file to its SHA-256. Rebranded project
files also retain their original source hash; third-party bytes are unchanged.
