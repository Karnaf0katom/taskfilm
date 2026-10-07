"""Offline craft gate for Jarvis <=60s reel scripts.

Every rule here is one line of the shot grammar in
``apps/taskfilm/docs/taskfilm-program/decisions/TRIAGE-2026-09-04-reel-factory.md``. It is deliberately
LEXICAL and deterministic: it decides whether a script obeys the grammar, never whether the words
are true. Truth is the evidence graph's job, and a claim with no evidence ref fails closed here.

The lexicons are written as word-boundary patterns rather than substrings because the failure that
actually happens is the opposite of the one people expect: not a marketing script sneaking through,
but honest narration being refused because it contained "build" or "install" as ordinary English.
A gate that refuses honest work gets switched off.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

# The lane already owns the "banned opening move" lexicon (hook.py, RL03). Importing it keeps ONE
# owner: a phrase added there is refused in the first three seconds here, with no second list to
# forget to update.
from hook import BANNED_OPENINGS, FRAMING_WORDS


VIOLATION_CODES = frozenset({
    "MISSING_ROLE",
    "BEAT_ORDER",
    "BEAT_TIMELINE",
    "PROOF_BEAT_COUNT",
    "BEAT_DURATION",
    "PROMISE_VO_LATE",
    "FIRST_OUTPUT_LATE",
    "CAPTION_TOO_LONG",
    "INTRO_IN_HOOK",
    "SETUP_FOOTAGE",
    "STATIC_BEAT",
    "MULTIPLE_MOTIONS",
    "BEAT_NO_LANE",
    "GENERATED_AS_EVIDENCE",
    "UNSUPPORTED_CLAIM",
    "MARKETING_FILLER",
    "DURATION_OUT_OF_BAND",
    "NO_HUMAN_OUTCOME",
    "PROMISE_NOT_CAPTURE",
    "PROMISE_DRIFT",
})

ROLE_ORDER = ("promise", "identity", "run-start", "proof", "bookend", "cta")
LANES = frozenset({"terminal", "browser", "diagram", "text-slide", "generated-broll"})
# Retention killer #1: "logo, intro, or welcome in the first three seconds."
_INTRO_RE = re.compile(
    "|".join([r"\b(?:logo|intro|introduction)\b"]
             + [r"\b" + re.escape(phrase) + r"\b" for phrase in sorted(BANNED_OPENINGS)]),
    re.IGNORECASE,
)

# Retention killer #2: "setup footage - npm install, build spinners, dependency downloads.
# Anything that is not payoff." Commands are matched as commands; narration is matched only on
# phrases that describe a setup EVENT, so "the index rebuilds in place" and "it downloads nothing"
# stay legal.
_SETUP_COMMAND_RE = re.compile("|".join([
    r"\bnpm\s+(?:install|ci)\b",
    r"\byarn\s+(?:install|add)\b",
    r"\bpnpm\s+(?:install|add)\b",
    r"\bpip3?\s+install\b",
    r"\bpoetry\s+install\b",
    r"\bbundle\s+install\b",
    r"\bcomposer\s+install\b",
    r"\b(?:apt|apt-get|brew|dnf|yum)\s+install\b",
    r"\bcargo\s+build\b",
    r"\bgo\s+(?:build|get)\b",
    r"\bmake\s+(?:install|build)\b",
    r"\bmvn\s+(?:install|package)\b",
    r"\bgradle\s+build\b",
    r"\bdocker\s+(?:build|pull)\b",
    r"\bgit\s+clone\b",
]), re.IGNORECASE)
_SETUP_NARRATION_RE = re.compile("|".join([
    r"\b(?:install|installing|installs)\s+(?:the\s+)?(?:dependencies|packages|modules|requirements)\b",
    r"\b(?:dependencies|packages|modules|requirements)\s+(?:finish\s+)?(?:download|downloading|installing|install)\b",
    r"\bdependency\s+(?:download|install)\w*\b",
    r"\bwaiting\s+for\s+(?:the\s+)?(?:build|install|download|dependencies)\b",
    r"\bbuild\s+(?:spinner|log|scroll)\b",
    r"\bwhile\s+(?:it|the\s+\w+)\s+(?:installs|downloads|compiles)\b",
]), re.IGNORECASE)

# Retention killer #3 names monotone, low-effort narration as the thing that "poisons the 'we
# really ran it' trust the whole format runs on". These are the words that tell on the writer.
# The first six are the operator's own BANNED_INPUT_WORDS from
# apps/video/director/doctrine/negatives.py, restated here for narration (that module is a
# generation-prompt negative list on a guarded surface, not an importable narration lexicon).
_MARKETING_RE = re.compile("|".join([
    r"\bcinematic\b", r"\bprofessional(?:[- ]grade)?\b", r"\bhigh[- ]quality\b",
    r"\bbeautiful\b", r"\bstunning\b", r"\bgorgeous\b",
    r"\brevolutionary\b", r"\bgame[- ]?chang(?:ing|er)\b", r"\bseamless(?:ly)?\b",
    r"\bblazing(?:ly)?\s+fast\b", r"\blightning[- ]?fast\b", r"\bcutting[- ]edge\b",
    r"\bstate[- ]of[- ]the[- ]art\b", r"\bincredible\b", r"\bamazing\b",
    r"\bmind[- ]?blowing\b", r"\bsupercharge[sd]?\b", r"\beffortless(?:ly)?\b",
    r"\bnext[- ]level\b", r"\bmust[- ]have\b", r"\binsane(?:ly)?\b", r"\bunbelievable\b",
    r"\bworld[- ]class\b", r"\b10x\b", r"\bunlocks?\s+the\s+power\b",
    r"\bthe\s+ultimate\b",
]), re.IGNORECASE)

CAPTION_WORD_LIMIT = 10
PROMISE_CAPTION_WORD_LIMIT = 4
MAX_STATIC_SECONDS = 2.5
PROOF_BEAT_BAND = (8.0, 12.0)
CEILING_SECONDS = 60.0
CAPTURE_LANES = frozenset({"terminal", "browser"})


@dataclass(frozen=True)
class Violation:
    """One validator finding."""

    code: str
    message: str
    beat_index: int | None = None


def validate_reel_script(
    script: Any,
    format_spec: Mapping[str, Any],
    *,
    evidence_graph: Mapping[str, Any],
) -> list[Violation]:
    """Return deterministic TRIAGE grammar violations for a reel script."""

    violations: list[Violation] = []
    beats = tuple(getattr(script, "beats", ()))
    _check_roles(beats, violations)
    _check_order(beats, violations)
    _check_timeline(beats, violations)
    _check_format_duration(script, format_spec, violations)
    evidence = _evidence_claims(evidence_graph)
    repo_terms = _repo_terms(script)

    for index, beat in enumerate(beats):
        role = getattr(beat, "role", "")
        lane = getattr(beat, "lane", "")
        claim_ids = tuple(getattr(beat, "claim_ids", ()) or ())
        text = _beat_text(beat)

        if lane not in LANES:
            violations.append(Violation("BEAT_NO_LANE", "beat declares no known visual lane", index))
        if len(tuple(getattr(beat, "motions", ()) or ())) > 1:
            violations.append(Violation("MULTIPLE_MOTIONS", "beat declares multiple motions", index))
        if lane == "generated-broll" and claim_ids:
            violations.append(Violation("GENERATED_AS_EVIDENCE", "generated b-roll cannot carry evidence claims", index))
        if _MARKETING_RE.search(text):
            violations.append(Violation("MARKETING_FILLER", "beat uses marketing filler", index))
        if _is_static(beat):
            violations.append(Violation(
                "STATIC_BEAT", "beat declares no visible change within 2.5s", index))
        if _is_setup_footage(beat):
            violations.append(Violation("SETUP_FOOTAGE", "setup footage is not a payoff beat", index))
        if len(str(getattr(beat, "caption", "")).split()) > CAPTION_WORD_LIMIT:
            violations.append(Violation("CAPTION_TOO_LONG", "caption is too long to read on a phone", index))
        if role == "promise":
            _check_promise(script, beat, index, repo_terms, violations)
        if role == "run-start":
            first_output = getattr(beat, "first_output_at_s", None)
            if first_output is None or float(first_output) > 10.0:
                violations.append(Violation("FIRST_OUTPUT_LATE", "first visible output must arrive by second 10", index))
        if role == "proof":
            _check_proof_beat(beat, index, evidence, violations)
        if claim_ids and any(claim_id not in evidence for claim_id in claim_ids):
            violations.append(Violation("UNSUPPORTED_CLAIM", "claim id has no evidence ref", index))

    return _dedupe(violations)


def _check_roles(beats: tuple[Any, ...], violations: list[Violation]) -> None:
    roles = [getattr(beat, "role", "") for beat in beats]
    for role in ROLE_ORDER:
        if role not in roles:
            violations.append(Violation("MISSING_ROLE", f"missing {role} beat"))
    proof_count = roles.count("proof")
    if proof_count not in {2, 3}:
        violations.append(Violation("PROOF_BEAT_COUNT", "script must carry 2-3 proof beats"))


def _check_order(beats: tuple[Any, ...], violations: list[Violation]) -> None:
    roles = [getattr(beat, "role", "") for beat in beats]
    filtered = [role for role in roles if role in ROLE_ORDER]
    indexes = [ROLE_ORDER.index(role) for role in filtered]
    if indexes != sorted(indexes):
        violations.append(Violation("BEAT_ORDER", "beats do not follow the TRIAGE order"))


def _check_timeline(beats: tuple[Any, ...], violations: list[Violation]) -> None:
    cursor = 0.0
    for index, beat in enumerate(beats):
        start = float(getattr(beat, "start_s", 0.0))
        duration = float(getattr(beat, "duration_s", 0.0))
        if abs(start - cursor) > 0.001:
            violations.append(Violation("BEAT_TIMELINE", "beats must be contiguous from zero", index))
        # Resync rather than return: one shifted beat must not hide a second, unrelated drift.
        cursor = start + duration


def _check_format_duration(script: Any, format_spec: Mapping[str, Any], violations: list[Violation]) -> None:
    band = format_spec.get("duration_band")
    total = float(getattr(script, "total_seconds", 0.0))
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        violations.append(Violation(
            "DURATION_OUT_OF_BAND", "format spec declares no duration band to check against"))
        return
    # 60s is a ceiling, not a target: a band whose top is above it is clipped, and a story that
    # runs dry early is legal anywhere inside its own band.
    low, high = float(band[0]), min(float(band[1]), CEILING_SECONDS)
    if not low <= total <= high:
        violations.append(Violation(
            "DURATION_OUT_OF_BAND",
            f"script runs {total:g}s; the {format_spec.get('id', '?')} band is {low:g}-{high:g}s"))


def _check_promise(
    script: Any,
    beat: Any,
    index: int,
    repo_terms: frozenset[str],
    violations: list[Violation],
) -> None:
    text = _beat_text(beat)
    if _INTRO_RE.search(text) or (repo_terms and _words(text) & repo_terms):
        violations.append(Violation("INTRO_IN_HOOK", "first three seconds cannot carry intro or repo name", index))
    if str(getattr(beat, "lane", "")) not in CAPTURE_LANES:
        violations.append(Violation("PROMISE_NOT_CAPTURE", "promise must be captured money-shot footage", index))
    # The anchor must be a CLAIM word. hook.FRAMING_WORDS are the words that present a payoff
    # without asserting anything about it, so an overlap of "watch"/"the" is not the narrator
    # keeping the authored promise. Lexical by design — the same honest limit hook.py records.
    promise_words = _content_words(str(getattr(script, "promise", "")))
    if promise_words and not (_content_words(text) & promise_words):
        violations.append(Violation("PROMISE_DRIFT", "promise beat must stay bound to the authored promise", index))
    first_vo = getattr(beat, "first_vo_word_at_s", None)
    if first_vo is None or float(first_vo) > 1.5:
        violations.append(Violation("PROMISE_VO_LATE", "first voiceover word must land by 1.5s", index))
    if len(str(getattr(beat, "caption", "")).split()) > PROMISE_CAPTION_WORD_LIMIT:
        violations.append(Violation("CAPTION_TOO_LONG", "promise caption must be four words or fewer", index))


def _check_proof_beat(
    beat: Any,
    index: int,
    evidence: Mapping[str, tuple[str, ...]],
    violations: list[Violation],
) -> None:
    claim_ids = tuple(getattr(beat, "claim_ids", ()) or ())
    if not claim_ids or any(claim_id not in evidence for claim_id in claim_ids):
        violations.append(Violation("UNSUPPORTED_CLAIM", "proof beat must bind to evidence", index))
    duration = float(getattr(beat, "duration_s", 0.0))
    if not PROOF_BEAT_BAND[0] <= duration <= PROOF_BEAT_BAND[1]:
        violations.append(Violation("BEAT_DURATION", "proof beats must run 8-12s", index))
    if str(getattr(beat, "lane", "")) == "terminal":
        human_outcome = str(getattr(beat, "human_outcome", "")).strip()
        caption = str(getattr(beat, "caption", "")).strip()
        command = str(getattr(beat, "command", "")).strip()
        caption_words = _words(caption)
        command_words = _words(command)
        if not human_outcome or (caption_words and command_words and caption_words <= command_words):
            violations.append(Violation("NO_HUMAN_OUTCOME", "terminal captions must state a human outcome", index))


def _evidence_claims(evidence_graph: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    claims: dict[str, tuple[str, ...]] = {}
    for claim in evidence_graph.get("claims", ()):
        if not isinstance(claim, Mapping):
            continue
        claim_id = claim.get("id")
        refs = claim.get("evidence_refs", ())
        if isinstance(claim_id, str) and claim_id and refs:
            claims[claim_id] = tuple(str(ref) for ref in refs)
    return claims


def _repo_terms(script: Any) -> frozenset[str]:
    identity = getattr(script, "identity", None) or {}
    repo = identity.get("repo") if isinstance(identity, Mapping) else None
    if not repo:
        return frozenset()
    parts = set(_words(str(repo)))
    if "/" in str(repo):
        parts.update(_words(str(repo).rsplit("/", 1)[-1]))
    return frozenset(parts)


def _is_static(beat: Any) -> bool:
    """Retention killer #3, applied to EVERY beat.

    JAR-R09050401 caught this scoped to proof beats only. The grammar does not scope it: "something
    visible must change every 3-4s - any static frame past ~2.5s is a drop-off". A beat shorter than
    the threshold cannot hold a static frame past it, so only longer beats must declare their change
    interval.
    """
    if float(getattr(beat, "duration_s", 0.0)) <= MAX_STATIC_SECONDS:
        return False
    visible = getattr(beat, "visible_change_every_s", None)
    return visible is None or float(visible) > MAX_STATIC_SECONDS


def _is_setup_footage(beat: Any) -> bool:
    """True when the beat FILMS setup, not when it merely says a word like "build"."""
    command = str(getattr(beat, "command", ""))
    if _SETUP_COMMAND_RE.search(command):
        return True
    return bool(_SETUP_NARRATION_RE.search(_beat_text(beat)))


def _beat_text(beat: Any) -> str:
    return " ".join((
        str(getattr(beat, "vo_line", "")),
        str(getattr(beat, "caption", "")),
    ))


def _content_words(text: str) -> set[str]:
    return _words(text) - FRAMING_WORDS


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _dedupe(violations: list[Violation]) -> list[Violation]:
    seen: set[tuple[str, int | None]] = set()
    result: list[Violation] = []
    for violation in violations:
        key = (violation.code, violation.beat_index)
        if key in seen:
            continue
        seen.add(key)
        result.append(violation)
    return result
