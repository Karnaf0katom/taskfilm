"""Prepare feature lessons, SaaS launches and GitHub reviews through existing owners.

This is a preproduction adapter, not an executor. It binds editorial choices to a
content-production-request/v1, routes beats through reel-lane, and exports briefs
for capture, HyperFrames and optional Blender work. Declared evidence references
are never reported as verified recordings. No source code, browser or model runs.

Story structure and reading-time guidance adapted from latent-spaces/brag (MIT).
The pinned sources, copyright and licence live in skills/exemplar_site_tour/references/brag.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import production_recipe
import production_request

VIDEO_ROOT = Path(__file__).resolve().parent.parent
if str(VIDEO_ROOT) not in sys.path:
    sys.path.insert(0, str(VIDEO_ROOT))
import videokit  # noqa: E402

SCHEMA = "product-story/v1"
PLAN_SCHEMA = "product-story-plan/v1"
UPSTREAM = Path(__file__).parent / "skills/exemplar_site_tour/references/brag"
FPS = 30
SIZES = {"16:9": [1920, 1080], "9:16": [1080, 1920], "1:1": [1080, 1080], "4:5": [1080, 1350]}
MODES = frozenset({"saas_launch", "github_review", "feature_demo"})
HANDOFF_KINDS = frozenset({"continuous_capture", "camera_follow", "match_cut", "transform", "intentional_cut"})
TONES = {
    "polished": "Confident pacing, restrained transitions, readable real UI.",
    "cinematic": "Measured reveals, strong product detail, restrained depth and light.",
    "app-store": "Clear feature demonstrations, clean reveals, one action at the close.",
}


class ProductStoryError(ValueError):
    """An editorial choice cannot be grounded in the supplied production request."""


def _object(value: Any, label: str, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, Mapping):
        raise ProductStoryError(f"{label}: expected an object")
    missing = required - set(value)
    unknown = set(value) - required - (optional or set())
    if missing or unknown:
        raise ProductStoryError(f"{label}: missing={sorted(missing)}, unknown={sorted(unknown)}")
    return copy.deepcopy(dict(value))


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ProductStoryError(f"{label}: expected 1–2000 characters")
    return value.strip()


def _seconds(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ProductStoryError(f"{label}: expected finite positive seconds")
    return float(value)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _upstream() -> dict:
    manifest = json.loads((UPSTREAM / "UPSTREAM.json").read_text())
    for row in manifest["files"]:
        if hashlib.sha256((UPSTREAM / row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ProductStoryError("pinned brag source hash mismatch")
    return manifest


def _repository(pack: Mapping | None, required: bool) -> dict | None:
    if pack is None:
        if required:
            raise ProductStoryError("github_review requires a pinned repo-pack from repo-lane/repo_pack.py")
        return None
    if not isinstance(pack, Mapping):
        raise ProductStoryError("repo_pack: expected an object")
    url = _text(pack.get("repository_url"), "repo_pack.repository_url")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", parsed.path)):
        raise ProductStoryError("repo_pack.repository_url: expected a public GitHub repository URL")
    commit = pack.get("resolved_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ProductStoryError("repo_pack.resolved_commit: expected a pinned 40-character commit")
    documents = pack.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ProductStoryError("repo_pack.documents: document hashes are required")
    for row in documents:
        if (not isinstance(row, Mapping) or not isinstance(row.get("path"), str)
                or not row["path"] or Path(row["path"]).is_absolute()
                or ".." in Path(row["path"]).parts or "\\" in row["path"]
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
            raise ProductStoryError("repo_pack.documents: unsafe path or missing SHA-256")
    return {
        "url": url.rstrip("/"), "commit": commit,
        "license_spdx": pack.get("license_spdx", "UNKNOWN"),
        "rights_status": pack.get("rights_status", "UNKNOWN"),
        "documents": copy.deepcopy(documents),
        "runtime_review": "not_performed",
        "security_review": "not_performed",
    }


def _scene(scene_id: str, kind: str, text: str, *, claims: list[dict] | None = None,
           source_id: str | None = None, capture_kind: str = "browser", blender: dict | None = None) -> dict:
    claims = claims or []
    beat = {"id": scene_id, "type": kind, "claim_ids": [row["id"] for row in claims]}
    if kind == "evidence":
        # Routing validates the requested lane, not the existence/semantics of these refs.
        beat.update(evidence_ids=[row["evidence_ref"] for row in claims], shot_lane=capture_kind)
    if blender is not None:
        beat.update(requested_engine="3d", justification=blender["justification"])
    route = videokit.load("reellane.beat_routing").route_beat(beat).to_json()
    # brag's 0.3s/word floor, plus time for entrance/exit. Product action needs a longer hold.
    hold = max(1.2, 0.3 * len(text.split()))
    minimum = max(3.0 if kind == "evidence" else 2.0, hold + 0.6)
    return {
        "id": scene_id, "type": kind, "on_screen_text": text,
        "claim_ids": beat["claim_ids"], "declared_evidence_refs": [c["evidence_ref"] for c in claims],
        "source_id": source_id, "route": route,
        "evidence_status": "capture_required" if kind == "evidence" else "not_product_proof",
        "minimum_frames": math.ceil(minimum * FPS), "settled_read_frames": math.ceil(hold * FPS),
    }


def _timeline(scenes: list[dict], seconds: float) -> list[dict]:
    target = round(seconds * FPS)
    if not math.isclose(target / FPS, seconds, rel_tol=0, abs_tol=1e-6):
        raise ProductStoryError("duration must fall on a 30fps frame boundary")
    floors = sum(row["minimum_frames"] for row in scenes)
    if target < floors:
        raise ProductStoryError(f"duration too short: this story needs at least {floors / FPS:g}s; shorten copy or use fewer moments")
    # Spend extra time on product use. No extra claim or scene is invented to fill a cut.
    flow_count = sum(row["type"] == "evidence" for row in scenes)
    share, remainder = divmod(target - floors, flow_count)
    result, start = [], 0
    for row in copy.deepcopy(scenes):
        duration = row.pop("minimum_frames")
        if row["type"] == "evidence":
            duration += share + int(remainder > 0)
            remainder = max(0, remainder - 1)
        row.update(start_frame=start, duration_frames=duration)
        start += duration
        result.append(row)
    return result


def _handoffs(value: Any, scenes: list[dict]) -> dict:
    """Validate authored boundary intent; this does not inspect rendered continuity."""
    pairs = [(before["id"], after["id"]) for before, after in zip(scenes, scenes[1:])]
    if not isinstance(value, list) or len(value) != len(pairs):
        raise ProductStoryError("handoffs: specify every adjacent scene boundary once, in timeline order")
    boundaries = []
    for index, (raw, pair) in enumerate(zip(value, pairs)):
        row = _object(raw, f"handoffs[{index}]", {"from", "to", "kind", "reason"}, {"carrier"})
        if (row["from"], row["to"]) != pair:
            raise ProductStoryError("handoffs: boundaries must match adjacent scene ids in timeline order")
        if not isinstance(row["kind"], str) or row["kind"] not in HANDOFF_KINDS:
            raise ProductStoryError(f"handoffs: kind must be one of {sorted(HANDOFF_KINDS)}")
        row["reason"] = _text(row["reason"], "handoff.reason")
        if row["kind"] == "intentional_cut":
            if "carrier" in row:
                raise ProductStoryError("handoffs: an intentional cut uses a reason rather than a carrier")
        else:
            row["carrier"] = _text(row.get("carrier"), "handoff.carrier")
        boundaries.append(row)
    return {"execution": "planned_only", "visual_verification": "not_performed", "boundaries": boundaries}


def build_product_story(request: Mapping, story: Mapping, *, repo_pack: Mapping | None = None,
                        brand_dir: Path | None = None) -> dict:
    """Produce a deterministic preproduction plan; reuse request, brand and beat owners."""
    validated = (production_request.validate_production_request(request) if brand_dir is None
                 else production_request.validate_production_request(request, brand_dir=brand_dir))
    request = validated.request
    if request["recipe"] != {"id": "product_launch_video", "format": "site_tour"}:
        raise ProductStoryError("product stories require the existing product_launch_video/site_tour recipe")
    story = _object(story, "story", {"schema_version", "mode", "product_name", "audience", "tone",
        "hook_claim_id", "moments", "durations_seconds"}, {"review", "blender", "handoffs"})
    if story["schema_version"] != SCHEMA or not isinstance(story["mode"], str) or story["mode"] not in MODES:
        raise ProductStoryError("expected product-story/v1 with mode saas_launch, github_review or feature_demo")
    if not isinstance(story["tone"], str) or story["tone"] not in TONES:
        raise ProductStoryError(f"tone must be one of {sorted(TONES)}")
    for key in ("product_name", "audience"):
        story[key] = _text(story[key], key)
    secrets = videokit.load("repolane.secrets_policy")
    secrets.require_safe_text(_json({"request": request, "story": story, "repo_pack": repo_pack}), "product story")
    repository = _repository(repo_pack, story["mode"] == "github_review")
    claims = {c["id"]: c for c in request["claims"]}
    if len(claims) != len(request["claims"]):
        raise ProductStoryError("claim ids must be unique")

    def claim(claim_id: Any) -> dict:
        if not isinstance(claim_id, str) or claim_id not in claims:
            raise ProductStoryError("story refers to an unknown claim id")
        fact = claims[claim_id]
        if story["mode"] == "github_review":
            prefix = f"{repository['url'].removesuffix('.git')}/blob/{repository['commit']}/"
            reference = fact["evidence_ref"]
            source_path = unquote(urlsplit(reference).path)
            prefix_path = urlsplit(prefix).path
            documents = {row["path"] for row in repository["documents"]}
            if (not reference.startswith(prefix) or urlsplit(reference).query
                    or source_path[len(prefix_path):] not in documents):
                raise ProductStoryError("GitHub review claims must cite a document in this pinned repo-pack")
        return fact

    hook = claim(story["hook_claim_id"])
    scenes = [_scene("hook", "explanation", hook["text"], claims=[hook])]
    sources = {s["id"]: s for s in request["sources"]}
    moments = story["moments"]
    minimum_moments = 1 if story["mode"] == "feature_demo" else 2
    if not isinstance(moments, list) or not minimum_moments <= len(moments) <= 3:
        choices = "one to three" if minimum_moments == 1 else "two or three"
        raise ProductStoryError(f"moments: select {choices} real product actions")
    captures, used = [], set()
    for index, raw in enumerate(moments):
        moment = _object(raw, f"moments[{index}]", {"id", "claim_id", "source_id", "capture_kind", "before", "action", "after"})
        mid = moment["id"]
        if not isinstance(mid, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", mid) or mid in used:
            raise ProductStoryError("moment ids must be unique lowercase slugs")
        used.add(mid)
        if not isinstance(moment["source_id"], str) or moment["source_id"] not in sources:
            raise ProductStoryError("moment source_id is absent from the production request")
        if not isinstance(moment["capture_kind"], str) or moment["capture_kind"] not in {"browser", "terminal"}:
            raise ProductStoryError("capture_kind must be browser or terminal")
        for key in ("before", "action", "after"):
            moment[key] = _text(moment[key], f"moment.{key}")
        fact = claim(moment["claim_id"])
        scene_id = f"flow-{mid}"
        scenes.append(_scene(scene_id, "evidence", fact["text"], claims=[fact],
                             source_id=moment["source_id"], capture_kind=moment["capture_kind"]))
        captures.append({**moment, "scene_id": scene_id, "source_uri": sources[moment["source_id"]]["uri"],
            "declared_evidence_ref": fact["evidence_ref"], "status": "capture_required",
            "acceptance": "Retain before/action/result frames, source hash and time range; verify the claim against the take."})
    review = None
    if story["mode"] == "github_review":
        review = _object(story.get("review"), "review", {"fit_claim_id", "limitation_claim_id"})
        if review["fit_claim_id"] == review["limitation_claim_id"]:
            raise ProductStoryError("GitHub review needs distinct fit and limitation claims")
        for role in ("fit", "limitation"):
            fact = claim(review[f"{role}_claim_id"])
            scenes.append(_scene(f"review-{role}", "explanation", fact["text"], claims=[fact]))
        review.update(scope="source_based_product_walkthrough", runtime_verified=False, security_audit=False)
    elif "review" in story:
        raise ProductStoryError("review is only valid in github_review mode")
    blender = None
    if "blender" in story:
        blender = _object(story["blender"], "blender", {"concept", "justification"})
        for key in blender:
            blender[key] = _text(blender[key], f"blender.{key}")
        scenes.append(_scene("brand-depth", "emotion", story["product_name"], blender=blender))
    cta = request["cta"]
    scenes.append(_scene("outro", "explanation", cta.get("label", story["product_name"])))
    handoff_plan = _handoffs(story["handoffs"], scenes) if "handoffs" in story else None
    durations = _object(story["durations_seconds"], "durations_seconds", {o["id"] for o in request["outputs"]})
    cap = _seconds(request["limits"]["max_duration_seconds"], "limits.max_duration_seconds")
    outputs = []
    for output in request["outputs"]:
        expected_kind = {"16:9": "landscape_video", "9:16": "vertical_short", "1:1": "square_video", "4:5": "vertical_short"}
        if output["aspect_ratio"] not in SIZES or output["kind"] != expected_kind[output["aspect_ratio"]] or output["count"] != 1:
            raise ProductStoryError("story outputs must be single video cuts with a matching aspect ratio")
        duration = _seconds(durations[output["id"]], "output duration")
        if duration > cap:
            raise ProductStoryError("output duration exceeds the production request limit")
        outputs.append({**output, "fps": FPS, "size": SIZES[output["aspect_ratio"]],
            "duration_seconds": duration, "scenes": _timeline(scenes, duration),
            "framing": "Recompose for this aspect; keep the active control and result legible. Do not blindly crop a desktop."})
    upstream = _upstream()
    route = production_recipe.plan("product_launch_video", brief=request["brief"])
    selected_claim_ids = {claim_id for scene in scenes for claim_id in scene["claim_ids"]}
    plan = {
        "schema_version": PLAN_SCHEMA, "phase": "preproduction", "execution": "planned_only",
        "ready_to_render": False, "provider_calls": 0, "spend_authorized": False,
        "request_id": request["request_id"], "request_digest": validated.request_digest,
        "story_digest": production_request.canonical_digest({"story": story, "repository": repository,
            "request_digest": validated.request_digest, "brand_digest": validated.brand_digest, "upstream": upstream}),
        "mode": story["mode"], "product_name": story["product_name"], "audience": story["audience"],
        "tone": {"preset": story["tone"], "direction": TONES[story["tone"]]},
        "recipe": route, "brand_identity": validated.brand_identity, "brand_digest": validated.brand_digest,
        "repository": repository, "review": review,
        "claims": [copy.deepcopy(c) for c in request["claims"] if c["id"] in selected_claim_ids],
        "claim_verification": "References are caller declarations; no asset resolution or semantic verification was performed.",
        "capture_requirements": captures, "outputs": outputs, "cta": copy.deepcopy(cta),
        "blender": None if blender is None else {**blender, "claim_ids": [], "status": "scene_authoring_required",
            "owner": "blender-lane", "exchange_owner": "edit-lane/exchange_publish.py",
            "rule": "Use brand depth or an illustrative transition. Product proof stays in the retained capture.",
            "brand_identity": validated.brand_identity},
        "audio": {"owner": "edit-lane", "music": "client-cleared music; select after direction review",
            "voiceover": "not_planned_by_this_adapter", "sfx": "sparse, aligned to actual interactions", "upstream_audio_imported": False},
        "upstream": upstream,
        "read_first": [*route["read_first"], "director/PRODUCT-STORY.md",
            *[str((UPSTREAM / f["path"]).relative_to(VIDEO_ROOT)) for f in upstream["files"] if f["path"].endswith(".md")]],
        "next_steps": [
            {"owner": "capture-lane/webrec.py", "action": "Discover controls and record the specified real product flow; retain provenance."},
            {"owner": "director/agent.py", "action": "For repository demos, use run_repo_demo_production and its evidence admission before narration/rendering."},
            {"owner": "hyperframes-lane/build_reel.py", "action": "Author composition from the briefs and verified take ranges; inspect each output aspect."},
            {"owner": "edit-lane/exchange_publish.py", "action": "Mix approved clips/audio, run QA and publish the editable exchange for FreeCut/Resolve review."},
        ],
    }
    if story["mode"] == "feature_demo":
        plan["teaching"] = {
            "goal_claim_id": hook["id"], "success_claim_id": captures[-1]["claim_id"],
            "step_scene_ids": [item["scene_id"] for item in captures],
            "direction": "State the goal, show each real action in order, and hold its result long enough to read. "
                         "Keep demonstrated interactions at natural speed; shorten idle waits with disclosed cuts. "
                         "Narration should name the visible control when the action happens.",
            "verification": "Capture and inspect the requested result; a lesson plan is not execution evidence.",
        }
    if handoff_plan is not None:
        plan["handoff_plan"] = handoff_plan
    return plan


def bundle_files(plan: Mapping) -> dict[str, str]:
    """Export agent-readable briefs and machine-readable plans without executing them."""
    common = [f"# {plan['product_name']}", "", "PREPRODUCTION ONLY — capture and output review are still required.", "",
        f"Audience: {plan['audience']}", f"Tone: {plan['tone']['direction']}",
        f"Brand digest: {plan['brand_digest']}", "", plan["claim_verification"], "",
        "Local policy takes precedence over upstream examples: product proof uses recorded UI/terminal footage.",
        "Simulated UI and 3D are illustrations only. Keep supplied brand fonts/colors; do not invent metrics.", ""]
    if "teaching" in plan:
        common += ["## Teaching direction", "", plan["teaching"]["direction"],
            plan["teaching"]["verification"], ""]
    composition = list(common)
    for output in plan["outputs"]:
        composition += [f"## {output['id']} — {output['aspect_ratio']} — {output['duration_seconds']:g}s", "", output["framing"], ""]
        for scene in output["scenes"]:
            composition.append(f"- {scene['start_frame'] / FPS:g}s + {scene['duration_frames'] / FPS:g}s: "
                f"{scene['id']} / {scene['route']['lane']}: {scene['on_screen_text']}")
        composition.append("")
    if "handoff_plan" in plan:
        composition += ["## Scene handoffs", "", "Authored intent only; continuity has not been checked in rendered frames.",
            "Apply the boundary plan to each aspect and inspect the actual outgoing/incoming frames.", ""]
        for boundary in plan["handoff_plan"]["boundaries"]:
            carrier = f"; carrier: {boundary['carrier']}" if "carrier" in boundary else ""
            composition.append(f"- {boundary['from']} → {boundary['to']}: {boundary['kind']}{carrier}. {boundary['reason']}")
        composition.append("")
    composition += ["## Brand identity", "", "```json", _json(plan["brand_identity"]).strip(), "```", "",
        "## Workflow sources", "", *[f"- apps/video/{p}" for p in plan["read_first"]], ""]
    capture = [*common, "## Real product takes", ""]
    for item in plan["capture_requirements"]:
        capture += [f"### {item['scene_id']} ({item['capture_kind']})", "", f"Source: {item['source_uri']}",
            f"Before: {item['before']}", f"Action: {item['action']}", f"Result to verify: {item['after']}",
            f"Claim: {item['claim_id']}", item["acceptance"], ""]
    review = [*common, "## Repository/source review", "", "```json", _json(plan["repository"]).strip(), "```", "",
        "Runtime behavior and security have not been assessed. Source assertions remain attributed assertions.", ""]
    for claim in plan["claims"]:
        review += [f"- {claim['id']}: {claim['text']} — {claim['evidence_ref']}"]
    blender = [*common, "## Blender handoff", "", "```json", _json(plan["blender"]).strip(), "```", "",
        "Use the existing blender-lane scene tools and OTIO exchange. This brief has not rendered a 3D clip.", ""]
    return {
        "product-story-plan.json": _json(plan), "composition-brief.md": "\n".join(composition),
        "capture-brief.md": "\n".join(capture), "source-review.md": "\n".join(review),
        "blender-brief.md": "\n".join(blender),
        "share-copy.txt": f"{plan['outputs'][0]['scenes'][0]['on_screen_text']} {plan['cta'].get('label', '')}\n".strip() + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--story", required=True, type=Path)
    parser.add_argument("--repo-pack", type=Path, help="existing pinned output from repo-lane/repo_pack.py")
    parser.add_argument("--brand-dir", type=Path, help="directory containing the named brand JSON and its font files")
    parser.add_argument("--out", type=Path, help="new directory for the reviewable preproduction bundle")
    args = parser.parse_args(argv)
    try:
        def read(path):
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ProductStoryError("input JSON exceeds 2 MiB")
            return json.loads(path.read_text(encoding="utf-8"))
        plan = build_product_story(read(args.request), read(args.story),
                                  repo_pack=read(args.repo_pack) if args.repo_pack else None,
                                  brand_dir=args.brand_dir)
        if args.out:
            files = bundle_files(plan)
            args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
            for name, content in files.items():
                (args.out / name).write_text(content, encoding="utf-8")
            print(_json({"execution": "planned_only", "bundle": str(args.out), "files": sorted(files),
                "ready_to_render": False}).strip())
        else:
            print(_json(plan), end="")
        return 0
    except (ValueError, OSError) as exc:
        print(f"product-story: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
