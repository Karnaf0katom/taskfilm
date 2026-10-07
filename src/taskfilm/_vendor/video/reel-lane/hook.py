"""Deterministic hook and cover-frame authorship for Jarvis reel variants.

The reel funnel starts here: write a checkable three-second promise before
capture work begins, or refuse the production.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


MAX_PROMISE_SECONDS = 3
MAX_PROMISE_WORDS = 12


# Neutral presentation verbs/connectors. They frame the payoff; they never assert a fact about it,
# so they are exempt from the claim check that every other word in a promise must pass.
FRAMING_WORDS = frozenset({
    # presentation verbs and connectors — they frame a payoff, they never assert anything about it
    "watch", "see", "from", "this", "that", "with", "into", "and", "the", "for", "now", "here",
    "your", "you", "its", "how", "what", "why", "when", "one", "just", "can", "will", "to",
    # ordinary stopwords. These were previously excluded by a `len(token) > 2` filter, which also
    # threw away real short claim words ("gif", "mp4", "3d") and made short use cases un-hookable
    # (JAR-R09041245). Naming the stopwords is the honest version of what the length test guessed at.
    "a", "an", "of", "in", "on", "at", "is", "are", "be", "as", "by", "or", "it", "up", "out",
})


# Retention killer #1 is a logo/intro/welcome in the first three seconds. These phrasings are
# refused wherever they appear — including when they arrive inside the use case and would otherwise
# be inherited by the generated promise.
BANNED_OPENINGS = frozenset({
    "welcome", "hi guys", "hey guys", "in this video", "today we", "let's take a look",
    "subscribe", "don't forget to",
})


class HookError(ValueError):
    """Raised when a use case cannot honestly support a reel hook."""


@dataclass(frozen=True)
class CoverFrameCandidate:
    """A possible first-frame cover for the authored hook."""

    label: str
    frame_at_s: int = 0
    visual_brief: str = ""
    is_cover: bool = False


@dataclass(frozen=True)
class Hook:
    """A checkable three-second promise and its opening-frame cover options."""

    promise: str
    cover_frame_at_s: int
    cover_candidates: tuple[CoverFrameCandidate, ...]
    repo: str | None = None
    use_case: str | None = None
    payoff: str | None = None


def author(use_case: Mapping[str, Any]) -> tuple[Hook, Hook, Hook]:
    """Return three deterministic, distinct hook candidates for a visual use case.

    The function is offline by design. If the use case cannot make a visual,
    checkable promise, it raises ``HookError`` instead of emitting a weak hook.
    """

    repo = _require_text(use_case, "repo")
    job = _require_text(use_case, "use_case")
    payoff = _require_text(use_case, "payoff")
    if use_case.get("payoff_is_visual") is not True:
        raise HookError("hook promise requires a visual payoff")

    # JAR-R09041240: this used to _strip_banned() the source text, which silently shipped mangled
    # copy and made the refusal below dead code. Refuse instead: a use case written in YouTube-intro
    # language is a use case someone has to rewrite, and quietly deleting the words hides that.
    for source, label in ((payoff, "payoff"), (job, "use_case")):
        low = source.lower()
        for banned in BANNED_OPENINGS:
            if banned in low:
                raise HookError(
                    f"{label} contains the banned opening move {banned!r}; rewrite the use case "
                    "rather than letting it become the first three seconds of the reel")
    payoff_phrase = _clean_payoff(payoff)
    job_phrase = _clean_job(job)
    promise_lines = _distinct_promises(payoff_phrase, job_phrase)
    covers = _cover_candidates(payoff_phrase)
    hooks = tuple(
        Hook(
            promise=promise,
            cover_frame_at_s=0,
            cover_candidates=covers,
            repo=repo,
            use_case=job,
            payoff=payoff,
        )
        for promise in promise_lines
    )
    # JAR-R09041242: author() used to emit candidates without ever consulting its own checker, so
    # the module could ship a promise it would itself refuse. A refusal that only fires when some
    # other caller remembers to ask is not a refusal.
    for cand in hooks:
        if not promise_is_supported(cand, use_case):
            raise HookError(f"authored a promise the use case does not support: {cand.promise!r}")
        low = cand.promise.lower()
        for banned in BANNED_OPENINGS:
            if banned in low:
                raise HookError(f"banned opening move in a promise: {cand.promise!r}")
    return hooks  # type: ignore[return-value]


def promise_is_supported(candidate: Hook, use_case: Mapping[str, Any]) -> bool:
    """LEXICAL support check: every claim-bearing word in the promise comes from the use case.

    HONEST LIMIT, recorded after JAR-R09041245 pushed on it. This is NOT semantic verification.
    It reliably refuses a promise that introduces claims the use case never made (the
    "will make you a millionaire" class, which is the failure that actually happens when a
    generator embellishes). It does NOT catch a promise that rearranges the use case's own words
    into a different assertion — "model turns into photo" for a photo-to-model repo — because
    deciding that requires understanding, not token membership.

    That check belongs where the evidence is: the promise is a claim like any other, and claims are
    bound to what the capture actually shows by the evidence graph (Taskfilm-23) once footage exists.
    Tracked as its own ticket rather than faked here; an offline module must not pretend to a
    judgement it cannot make.
    """

    if not isinstance(candidate, Hook):
        return False
    if use_case.get("payoff_is_visual") is not True:
        return False
    payoff = use_case.get("payoff")
    job = use_case.get("use_case")
    if not isinstance(payoff, str) or not isinstance(job, str):
        return False
    # JAR-R09041233: this used to short-circuit on `candidate.payoff`, a copy of the input the
    # Hook was carrying, so the function that exists to check the PROMISE returned an answer
    # without ever reading it. Support is decided by the promise text or it is not decided.

    promise_tokens = set(_words(candidate.promise))
    supported_tokens = set(_words(f"{payoff} {job}"))
    # FRAMING words present the payoff without asserting anything about it ("watch this", "from X
    # to Y"). They carry no claim, so requiring the use case to contain them would refuse every
    # readable hook. Every OTHER meaningful token is a claim and must be supported.
    # JAR-R09041245: `len(t) > 2` silently dropped every short word, so a use case written in
    # short words ("cut a gif from a mp4") produced an empty claim set and could never be hooked.
    # Framing membership is the real filter; length was a proxy for it.
    claim_tokens = {t for t in promise_tokens if t not in FRAMING_WORDS}
    if not claim_tokens:
        return False
    if not claim_tokens.issubset(supported_tokens):
        return False
    # A promise built only from framing plus one incidental word is not a promise about THIS repo.
    return bool(claim_tokens & set(_words(payoff)))


def _require_text(use_case: Mapping[str, Any], field: str) -> str:
    value = use_case.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HookError(f"{field} must be a non-empty string")
    return value.strip()


def _distinct_promises(payoff_phrase: str, job_phrase: str) -> tuple[str, str, str]:
    candidates = (
        f"Watch {payoff_phrase}",
        f"See {payoff_phrase}",
        f"From {job_phrase} to {payoff_phrase}",
    )
    shortened = tuple(_fit_promise(line) for line in candidates)
    if len(set(shortened)) != 3:
        shortened = (
            _fit_promise(f"Watch {payoff_phrase}"),
            _fit_promise(f"Now {payoff_phrase}"),
            _fit_promise(f"Proof: {payoff_phrase}"),
        )
    if len(set(shortened)) != 3:
        raise HookError("could not write three distinct hook promises")
    return shortened  # type: ignore[return-value]


def _cover_candidates(payoff_phrase: str) -> tuple[CoverFrameCandidate, CoverFrameCandidate, CoverFrameCandidate]:
    return (
        CoverFrameCandidate("cover", 0, f"First frame shows {payoff_phrase}", True),
        CoverFrameCandidate("alternate-tight", 0, f"Tight first-frame proof of {payoff_phrase}", False),
        CoverFrameCandidate("alternate-context", 0, f"Context first-frame proof of {payoff_phrase}", False),
    )


def _clean_payoff(text: str) -> str:
    text = _strip_lead_article(text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        raise HookError("payoff must describe a visible outcome")
    return text


def _clean_job(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        raise HookError("use_case must describe the viewer setup")
    return text


def _fit_promise(text: str) -> str:
    words = text.split()
    if len(words) <= MAX_PROMISE_WORDS:
        return text
    return " ".join(words[:MAX_PROMISE_WORDS]).rstrip(" ,;:")


def _strip_lead_article(text: str) -> str:
    return re.sub(r"^(a|an|the)\s+", "", text.strip(), flags=re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(_words(text))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
