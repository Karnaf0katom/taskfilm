# Record a reviewed animation

After watching the encoded movie (and listening when it has audio), explicitly
record your review acknowledgement:

```sh
taskfilm record-review ./project --movie ./film.mp4 --history ./treatment-history.json --reviewer "Your Name" --confirm-reviewed
```

The project must contain its `ANIMATION-PLAN.json` from `taskfilm animate`.
The command checks the animation schema and selected treatment against the shared
catalog, hashes the actual plan and movie bytes, and uses ffprobe to check for a
nonempty video stream with positive dimensions and duration. Install ffmpeg,
which includes ffprobe, before running it. The probe has a 20-second timeout.

`--confirm-reviewed` records the caller's acknowledgement. The technical checks
do not establish that anyone watched, listened, approved quality, or that this
movie was rendered from these source files. The command records the supplied
movie and plan identities together; the caller owns that association.

New history uses `taskfilm-treatment-history/v1`. Existing planned and failed
events and additional fields are retained. Reviewed events feed the shared
selector: pass this file to `taskfilm treatments --history FILE` or
`taskfilm animate PROJECT --history FILE` to avoid recently reviewed structures.
Recording the same movie again is a byte-for-byte no-op. A different plan or
treatment for an already recorded movie is refused. Showreels combine treatments
and cannot be recorded as a single treatment.

Malformed histories, unknown treatments, contradictory fingerprints, invalid
movies and missing acknowledgements fail without changing history. A history
with 200 events cannot accept another event; archive it explicitly rather than
silently deleting prior reviews. Parent directories must already exist.

Writes use a persistent `.lock` sidecar with a ten-second acquisition timeout
and an atomic replacement in the same directory. This release is tested on
Linux and requires POSIX file locking; unsupported platforms fail clearly
before any mutation. Concurrent record-review
writers serialize and reread history inside the lock. Other tools writing this
file must cooperate with the same lock; a detected external change before
replacement is refused, but arbitrary writers ignoring the lock cannot be
fully coordinated. Keep the sidecar file in place. History symlinks are refused.
The command does not modify the animation plan or movie.
