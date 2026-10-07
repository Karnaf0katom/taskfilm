# Evidence-backed demo companion

`demo_package.py` adapts an existing accepted `webrec.py` take to an offline,
single HTML walkthrough with playable embedded footage, chapter seeking, optional
PNG screenshots, assertion downloads, copyable evidenced commands and retained
license/source attribution. It calls capture-lane's provenance owner and probes
the MP4; it never records, renders, runs commands, buys narration or publishes.
This is a generated educational artifact, not a new Taskfilm app route.

```sh
python3 apps/video/reel-lane/demo_package.py --evidence /path/demo.json --out /path/new-package
```

API: `package_from_manifest(manifest_path, out_dir)` or
`build_package(take_dir, evidence_manifest_path, out_dir)`. Outputs `PACKAGE.json`
and `walkthrough.html`; output must not exist. Integrators can retain both files
as stage artifacts. Each package explicitly says `companion_ready_reel_unrendered`,
`rendered_deliverable: false`, `narration_policy: silent`. Its `reel_plan` gives
argument arrays for the existing capture-lane `reel.py --silent --check` followed
by `npm run render` in that output. This plan is not execution evidence.

Input JSON (replace every example with actual retained evidence):

```json
{
  "schema": "demo-evidence/v1",
  "title": "Import and split a clip",
  "take_dir": "takes/accepted",
  "repository": {"url": "https://github.com/owner/repo", "commit": "FULL_40_CHARACTER_LOWERCASE_COMMIT"},
  "source_label": "ai-platform fork / working tree, with capture revision disclosed",
  "license": {"spdx": "MIT", "artifact": {"path": "LICENSE", "sha256": "SHA256_OF_LICENSE"}},
  "take": {"session_sha256": "SHA256_OF_SESSION_JSON", "screen_sha256": "SHA256_OF_SCREEN_MP4"},
  "expected_page_errors": [{"match": "SUBSTRING_OF_THE_LOGGED_ERROR", "why": "named reason the app logs this every run"}],
  "steps": [{
    "id": "split", "title": "Split the clip", "at_s": 12.5,
    "claim": "Two timeline segments are visible",
    "evidence": {"path": "split-assertion.json", "sha256": "SHA256_OF_ASSERTION"}
  }],
  "useful_result": {"step_id": "split", "claim": "Two timeline segments are visible"}
}
```

Every step's assertion JSON must contain `schema: demo-assertion/v1`, matching
`step_id`, `claim`, `at_s` and `take` hashes; `passed: true`; equal `expected` and
`observed` values; `method: runtime_assertion` or `visual_review`; and a nonempty
`producer` identifying who/what made the observation. Optional step `command`
requires assertion `command_execution: {command: <exact string>, exit_code: 0}`.
Optional step `screenshot: {path, sha256}` must identify retained PNG bytes.
Optional top-level `expected_page_errors: [{match, why}]` waives a retained
`session.json` page error only when its text contains `match`; every waived error is
carried into `PACKAGE.json.page_errors_waived` and named on the companion page, never
silently dropped. An unmatched page error still refuses packaging (same contract as
`repo-lane/cohort.py`'s gate — a waiver must be argued for in writing, per-app).
Evidence paths must be relative to the manifest directory: absolute paths, parent
traversal and symlinks (including directory ancestors) are rejected. `take_dir` may
be an absolute trusted invocation path, but every take stream must be a direct,
non-symlink retained file within that directory. Do not point inputs at secret-bearing
logs. The API accepts `proof_limit` (default 8 MiB, hard maximum 16 MiB) and
`take_limit` (default 256 MiB, hard maximum 512 MiB). The manifest is capped at
2 MiB. Take files are size-checked before calling the provenance assembler; total
take + manifest + referenced proof input bytes may not exceed `take_limit`.
The self-contained HTML expands video bytes through base64, so output is larger
than its retained input. Retained source files must remain immutable during packaging.

These receipts are attributed attestations, not cryptographic proof of actual
execution. Packaging verifies byte identity and contract consistency; it cannot
independently authenticate a producer, decide whether a visual claim is true, or
clear redistribution rights. Do not synthesize passing assertions from prose.
License notice bytes are included intact; dependency/asset review stays with the
existing rights owner. No claim that a root SPDX label clears all components.

V1 rejects `enhancement`: keep a verified baseline first, then independently
package the retained after-take and patch evidence through the future comparison
adapter. It must never label an unfilmed improvement as demonstrated. Final reel
QA and 45–60 second delivery acceptance are separate downstream checks.

Verification: `python3 -m pytest -q -p no:cacheprovider apps/video/reel-lane/tests/test_demo_package.py`.

## Finished release showcase

The same artifact owner accepts `--showcase <manifest.json> --out <new-directory>`
to package already-rendered movies and standalone distribution downloads as a
portable release document. This adds no app route, editor or renderer. It produces
`index.html`, local movie/poster assets, download archives and `SHOWCASE.json`.
The existing take companion API and evidence requirements are unchanged.

The manifest uses `schema: showcase-evidence/v1`, `title`, `intro`, `version`,
`movies` and `downloads`. Each movie has a relative `path`, `sha256`, `label`,
`description`, `seconds`, `width`, `height` and `fps`; an optional PNG `poster`
has its own `path` and `sha256`. Each download has `path`, `sha256` and `label`.
Movies may also supply `app_description` and `taskfilm_description` to explain
the featured tool and how its film was made, plus up to three `links` with
`label` and a public HTTPS `url`. Text is escaped; credential-bearing or
non-HTTPS resource links are rejected. Existing manifests remain valid.
Only MP4 movies and ZIP/wheel/tar.gz downloads are accepted. Inputs stay within
the manifest directory, reject symlinks/traversal and share a 256 MiB byte budget.
The owner rehashes every asset and probes duration, geometry and frame rate before
atomically writing a new output. It retains optional `source_evidence` in the
receipt; producer approval is not relabelled as independent verification.

Verification also includes `tests/test_release_showcase.py`.
