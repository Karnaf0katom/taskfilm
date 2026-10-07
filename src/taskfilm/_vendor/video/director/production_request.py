"""Versioned, client-neutral production request validation.

This module binds a request to existing recipe and brand owners without copying either registry.
Validation is intentionally offline and happens before any dispatcher/provider call.  The only
filesystem reads are the existing mix brand pack and its declared font files.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import format_select
import production_recipe


SCHEMA_VERSION = "content-production-request/v1"
VIDEO_ROOT = Path(__file__).resolve().parent.parent
MIX_ROOT = VIDEO_ROOT / "mix"
if str(MIX_ROOT) not in sys.path:
    sys.path.insert(0, str(MIX_ROOT))

from build_mix import brand_render_identity, load_brand_pack  # noqa: E402


ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$")
KEYWORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")
CTA_TYPES = frozenset({"link", "booking", "purchase", "follow", "keyword", "none"})
OUTPUT_KINDS = frozenset(
    {
        "vertical_short",
        "landscape_video",
        "square_video",
        "caption_file",
        "edit_package",
        "interactive_deck",
    }
)
ASPECT_RATIOS = frozenset({"9:16", "16:9", "1:1", "4:5", "source"})

ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "workspace_id",
        "client",
        "brief",
        "recipe",
        "brand",
        "sources",
        "references",
        "claims",
        "language",
        "outputs",
        "cta",
        "limits",
        "approvals",
        "cost",
    }
)


class RequestValidationError(ValueError):
    """The request cannot safely cross the dispatch boundary."""


@dataclass(frozen=True)
class ValidatedProductionRequest:
    request: dict[str, Any]
    request_digest: str
    brand_digest: str
    brand_identity: dict[str, Any]

    def receipt(self) -> dict[str, Any]:
        approvals = self.request["approvals"]
        return {
            "schema_version": self.request["schema_version"],
            "request_id": self.request["request_id"],
            "workspace_id": self.request["workspace_id"],
            "recipe_id": self.request["recipe"]["id"],
            "format_id": self.request["recipe"]["format"],
            "brand_ref": {
                "workspace_id": self.request["brand"]["workspace_id"],
                "pack": self.request["brand"]["pack"],
                "digest": self.brand_digest,
            },
            "request_digest": self.request_digest,
            "outputs": [row["id"] for row in self.request["outputs"]],
            "approval_state": {
                "content": approvals["content"] is not None,
                "spend": approvals["spend"] is not None,
                "cost": self.request["cost"]["status"],
            },
            "brand_render_identity": copy.deepcopy(self.brand_identity),
            "proof": "offline_validation_only",
        }


def _fail(path: str, message: str) -> None:
    raise RequestValidationError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], path: str, required: set[str], optional: set[str] | None = None) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        _fail(path, f"missing fields {missing}")
    if unknown:
        _fail(path, f"unknown fields {unknown}")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    return value.strip()


def _id(value: Any, path: str) -> str:
    result = _text(value, path)
    if not ID_RE.fullmatch(result):
        _fail(path, "must be a lowercase stable id")
    return result


def _positive_int(value: Any, path: str, *, allow_zero: bool = False) -> int:
    floor = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < floor:
        _fail(path, f"must be an integer >= {floor}")
    return value


def _positive_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        _fail(path, "must be a positive number")
    return float(value)


def _ref(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    result = _text(value, path)
    parsed = urlsplit(result)
    if not parsed.scheme:
        _fail(path, "must be an absolute reference URI")
    return result


def _workspace_ref(value: Any, workspace_id: str, path: str) -> str:
    result = _ref(value, path)
    parsed = urlsplit(result)
    if parsed.scheme != "workspace" or parsed.netloc != workspace_id:
        _fail(path, f"must be scoped to workspace {workspace_id!r}")
    if not parsed.path.strip("/") or ".." in parsed.path.split("/"):
        _fail(path, "must name a safe workspace asset path")
    return result


def _validate_client(raw: Any) -> None:
    row = _mapping(raw, "client")
    _exact_fields(row, "client", {"id", "name"})
    _id(row["id"], "client.id")
    _text(row["name"], "client.name")


def _validate_recipe(raw: Any, source_kinds: set[str]) -> None:
    row = _mapping(raw, "recipe")
    _exact_fields(row, "recipe", {"id", "format"})
    recipe_id = _id(row["id"], "recipe.id")
    try:
        recipe = production_recipe.get(recipe_id)
    except KeyError as exc:
        _fail("recipe.id", str(exc))
    format_id = _id(row["format"], "recipe.format")
    if format_id not in format_select.FORMAT_REGISTRY:
        _fail("recipe.format", f"unknown format {format_id!r}")
    missing_inputs = sorted(set(recipe.requires) - source_kinds)
    if missing_inputs:
        _fail("recipe.id", f"recipe requires source kinds {missing_inputs}")


def _validate_sources(raw: Any, workspace_id: str) -> set[str]:
    if not isinstance(raw, list) or not raw:
        _fail("sources", "must contain at least one source")
    kinds: set[str] = set()
    ids: set[str] = set()
    for index, item in enumerate(raw):
        path = f"sources[{index}]"
        row = _mapping(item, path)
        _exact_fields(row, path, {"id", "workspace_id", "kind", "uri", "rights"})
        source_id = _id(row["id"], f"{path}.id")
        if source_id in ids:
            _fail(f"{path}.id", "must be unique")
        ids.add(source_id)
        if row["workspace_id"] != workspace_id:
            _fail(f"{path}.workspace_id", "cross-workspace source is forbidden")
        kind = _text(row["kind"], f"{path}.kind").lower()
        if kind not in production_recipe.INPUT_KINDS:
            _fail(f"{path}.kind", f"unknown input kind {kind!r}")
        kinds.add(kind)
        _workspace_ref(row["uri"], workspace_id, f"{path}.uri")
        rights = _mapping(row["rights"], f"{path}.rights")
        _exact_fields(rights, f"{path}.rights", {"status", "evidence_ref"})
        if rights["status"] != "approved":
            _fail(f"{path}.rights.status", "must be 'approved' before dispatch")
        _ref(rights["evidence_ref"], f"{path}.rights.evidence_ref")
    return kinds


def _validate_references(raw: Any, workspace_id: str) -> None:
    if not isinstance(raw, list):
        _fail("references", "must be a list")
    for index, item in enumerate(raw):
        path = f"references[{index}]"
        row = _mapping(item, path)
        _exact_fields(row, path, {"id", "workspace_id", "uri", "approved", "approval_ref"})
        _id(row["id"], f"{path}.id")
        if row["workspace_id"] != workspace_id:
            _fail(f"{path}.workspace_id", "cross-workspace reference is forbidden")
        _workspace_ref(row["uri"], workspace_id, f"{path}.uri")
        if row["approved"] is not True:
            _fail(f"{path}.approved", "must be true before dispatch")
        _ref(row["approval_ref"], f"{path}.approval_ref")


def _validate_claims(raw: Any) -> None:
    if not isinstance(raw, list):
        _fail("claims", "must be a list")
    for index, item in enumerate(raw):
        path = f"claims[{index}]"
        row = _mapping(item, path)
        _exact_fields(row, path, {"id", "text", "approved", "evidence_ref"})
        _id(row["id"], f"{path}.id")
        _text(row["text"], f"{path}.text")
        if row["approved"] is not True:
            _fail(f"{path}.approved", "must be true before dispatch")
        _ref(row["evidence_ref"], f"{path}.evidence_ref")


def _validate_outputs(raw: Any, max_outputs: int) -> None:
    if not isinstance(raw, list) or not raw:
        _fail("outputs", "must contain at least one requested output")
    ids: set[str] = set()
    total = 0
    for index, item in enumerate(raw):
        path = f"outputs[{index}]"
        row = _mapping(item, path)
        _exact_fields(row, path, {"id", "kind", "aspect_ratio", "count"})
        output_id = _id(row["id"], f"{path}.id")
        if output_id in ids:
            _fail(f"{path}.id", "must be unique")
        ids.add(output_id)
        if row["kind"] not in OUTPUT_KINDS:
            _fail(f"{path}.kind", f"unknown output kind {row['kind']!r}")
        if row["aspect_ratio"] not in ASPECT_RATIOS:
            _fail(f"{path}.aspect_ratio", f"unsupported aspect ratio {row['aspect_ratio']!r}")
        total += _positive_int(row["count"], f"{path}.count")
    if total > max_outputs:
        _fail("outputs", f"requested count {total} exceeds limits.max_outputs {max_outputs}")


def _validate_cta(raw: Any) -> None:
    row = _mapping(raw, "cta")
    _exact_fields(row, "cta", {"type"}, {"label", "target", "keyword"})
    cta_type = row["type"]
    if cta_type not in CTA_TYPES:
        _fail("cta.type", f"must be one of {sorted(CTA_TYPES)}")
    if cta_type == "none":
        extras = sorted(set(row) - {"type"})
        if extras:
            _fail("cta", f"none CTA cannot carry fields {extras}")
        return
    _text(row.get("label"), "cta.label")
    if cta_type in {"link", "booking", "purchase"}:
        target = _text(row.get("target"), "cta.target")
        parsed = urlsplit(target)
        if parsed.scheme != "https" or not parsed.netloc:
            _fail("cta.target", "must be an https URL")
    elif cta_type == "follow":
        _text(row.get("target"), "cta.target")
    elif cta_type == "keyword":
        keyword = _text(row.get("keyword"), "cta.keyword")
        if not KEYWORD_RE.fullmatch(keyword):
            _fail("cta.keyword", "must be 2-32 letters, digits, underscore, or hyphen")
    if cta_type != "keyword" and "keyword" in row:
        _fail("cta.keyword", "is valid only for keyword campaigns")
    if cta_type == "keyword" and "target" in row:
        _fail("cta.target", "is not used by keyword campaigns")


def _validate_limits(raw: Any) -> int:
    row = _mapping(raw, "limits")
    _exact_fields(row, "limits", {"max_outputs", "max_duration_seconds", "max_revisions", "max_attempts"})
    max_outputs = _positive_int(row["max_outputs"], "limits.max_outputs")
    _positive_number(row["max_duration_seconds"], "limits.max_duration_seconds")
    _positive_int(row["max_revisions"], "limits.max_revisions", allow_zero=True)
    _positive_int(row["max_attempts"], "limits.max_attempts")
    return max_outputs


def _validate_approvals(raw: Any) -> None:
    row = _mapping(raw, "approvals")
    _exact_fields(row, "approvals", {"content", "spend"})
    _ref(row["content"], "approvals.content", nullable=True)
    _ref(row["spend"], "approvals.spend", nullable=True)


def _validate_cost(raw: Any, approvals: Mapping[str, Any]) -> None:
    row = _mapping(raw, "cost")
    _exact_fields(row, "cost", {"status", "currency", "cap"})
    if row["status"] not in {"unknown", "estimated", "approved"}:
        _fail("cost.status", "must be unknown, estimated, or approved")
    if row["status"] == "unknown":
        if row["currency"] is not None or row["cap"] is not None:
            _fail("cost", "unknown cost must keep currency and cap null")
        return
    currency = _text(row["currency"], "cost.currency")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        _fail("cost.currency", "must be a three-letter uppercase currency")
    _positive_number(row["cap"], "cost.cap")
    if row["status"] == "approved" and approvals["spend"] is None:
        _fail("approvals.spend", "is required when cost.status is approved")


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_production_request(raw: Mapping[str, Any], *, brand_dir: Path | None = None) -> ValidatedProductionRequest:
    request = copy.deepcopy(dict(_mapping(raw, "request")))
    _exact_fields(request, "request", set(ROOT_FIELDS))
    if request["schema_version"] != SCHEMA_VERSION:
        _fail("schema_version", f"must equal {SCHEMA_VERSION!r}")
    _id(request["request_id"], "request_id")
    workspace_id = _id(request["workspace_id"], "workspace_id")
    _validate_client(request["client"])
    _text(request["brief"], "brief")
    source_kinds = _validate_sources(request["sources"], workspace_id)
    _validate_recipe(request["recipe"], source_kinds)

    brand = _mapping(request["brand"], "brand")
    _exact_fields(brand, "brand", {"workspace_id", "pack"})
    if brand["workspace_id"] != workspace_id:
        _fail("brand.workspace_id", "cross-workspace brand is forbidden")
    pack_name = _id(brand["pack"], "brand.pack")
    try:
        pack = (load_brand_pack({"brand_pack": pack_name}, MIX_ROOT) if brand_dir is None
                else load_brand_pack({"brand_pack": pack_name}, brand_dir=brand_dir))
    except (SystemExit, OSError, json.JSONDecodeError) as exc:
        _fail("brand.pack", str(exc))

    _validate_references(request["references"], workspace_id)
    _validate_claims(request["claims"])
    language = _text(request["language"], "language")
    if not LANGUAGE_RE.fullmatch(language):
        _fail("language", "must be a BCP-47 language tag")
    max_outputs = _validate_limits(request["limits"])
    _validate_outputs(request["outputs"], max_outputs)
    _validate_cta(request["cta"])
    _validate_approvals(request["approvals"])
    _validate_cost(request["cost"], request["approvals"])

    identity = brand_render_identity(pack)
    return ValidatedProductionRequest(
        request=request,
        request_digest=canonical_digest(request),
        brand_digest=canonical_digest(identity),
        brand_identity=identity,
    )


def load_request(path: str | Path) -> ValidatedProductionRequest:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestValidationError(f"request file {source}: {exc}") from exc
    return validate_production_request(raw)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="path to a content-production-request/v1 JSON file")
    args = parser.parse_args(argv)
    print(json.dumps(load_request(args.request).receipt(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
