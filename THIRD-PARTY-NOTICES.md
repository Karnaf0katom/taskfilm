# Third-party notices

Original Taskfilm code, including the selected project-owned Humanflow modules,
is distributed under the [MIT License](LICENSE). Third-party material retains
the separate licenses and notices listed below.

## Included material

- **latent-spaces/brag**, MIT, pinned at
  `57ce4c9bb912f01a0078b154318bf67c5cbf780f`. The planner's source and reading-time
  guidance retain the copyright, full licence, pinned source hashes and three
  reference files under
  `src/taskfilm/_vendor/video/director/skills/exemplar_site_tour/references/brag/`.
- **Manrope**, SIL Open Font License 1.1. The original font and full retained
  notice are under
  `src/taskfilm/_vendor/video/hyperframes-lane/product-motion/assets/`.
  Source: <https://github.com/sharanda/manrope>.
- **Geist Mono**, SIL Open Font License 1.1. Its font and full retained notice
  accompany Manrope in the same directory. Source: <https://github.com/vercel/geist-font>.

## Separately installed runtime dependencies

- PyYAML (MIT), Pillow (HPND), Playwright (Apache-2.0); installed by pip, not
  copied into the source export.
- Chromium and FFmpeg are installed separately. Their distribution and codec
  terms depend on the chosen build; retain the notices supplied with that build.
- NumPy (BSD-3-Clause) and SciPy (BSD-3-Clause) are optional, separately installed
  dependencies of the original product-motion owner.
- HyperFrames `0.8.134` (Apache-2.0) is installed by npm for the generated render
  project. Source: <https://github.com/heygen-com/hyperframes>.
- GSAP `3.14.2` is loaded by the existing composition adapter from its pinned
  jsDelivr URL. It is not relicensed as Taskfilm code or included in this export;
  its own licence applies: <https://gsap.com/standard-license/>.

## Apps shown in the OSS showcase recordings

The original recipes operate these apps through their own UI. Their code is
not copied into Taskfilm. The accompanying source-reference inventory distinguishes
pinned documentation from the hosted editor's actual runtime revision.

- **Excalidraw**, MIT: <https://github.com/excalidraw/excalidraw>.
- **drawDB**, AGPL-3.0: <https://github.com/drawdb-io/drawdb>.
- **Penpot**, MPL-2.0: <https://github.com/penpot/penpot>, self-hosted release 2.18.2.

The recordings use original sample diagrams, SQL and interface designs. Native
exports and result screenshots accompany the demo evidence. No endorsement by
these projects is implied.
