"""Durable scheduled social posts with checkpoints and conservative retry semantics.

Workers are explicit: `work --execute` sends posts, `work` only previews due jobs.
Ambiguous publication responses never trigger a blind duplicate publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .media import digest, probe


class APIError(RuntimeError):
    def __init__(self, message, *, status=None, definitive=False):
        super().__init__(message)
        self.status = status
        self.definitive = definitive


class UncertainPublication(RuntimeError):
    pass


class Waiting(RuntimeError):
    pass


def request_json(url: str, *, method: str = "GET", data: dict | None = None,
                 headers: dict | None = None) -> dict:
    body = None if data is None else urlencode(data).encode()
    request = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # No provider body or URL in logs: they can contain tokens or signed URLs.
        raise APIError(f"Provider rejected request (HTTP {exc.code})", status=exc.code,
                       definitive=400 <= exc.code < 500 and exc.code != 408) from None
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise APIError("Provider response unavailable or invalid") from None
    if not isinstance(result, dict) or "error" in result:
        raise APIError("Provider returned an error response")
    return result


def _https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def validate_manifest(path: Path) -> dict:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Publish manifest must be a JSON object")
    allowed = {"schema", "video", "video_url", "title", "caption", "attribution", "target",
               "scheduled_at", "contains_synthetic_media", "made_for_kids", "privacy", "audio_receipt"}
    if raw.get("schema") != "taskfilm-publish/v1" or set(raw) - allowed:
        raise ValueError("Expected a taskfilm-publish/v1 manifest with supported fields")
    video = (path.parent / raw["video"]).resolve()
    info = probe(video)
    if not any(s.get("codec_type") == "video" for s in info["streams"]):
        raise ValueError("Publish asset has no video stream")
    target = raw["target"]
    if not isinstance(target, dict):
        raise ValueError("Publishing target must be an object")
    platform = target.get("platform")
    if platform not in {"instagram", "facebook", "youtube"}:
        raise ValueError("Platform must be instagram, facebook, or youtube")
    allowed_target = {"platform", "account_id", "token_env", "graph_version", "credentials_env"}
    if set(target) - allowed_target or not re.fullmatch(r"[a-zA-Z0-9_-]+", str(target.get("account_id", ""))):
        raise ValueError("Target needs an explicit account ID and environment references, not secrets")
    if platform in {"instagram", "facebook"}:
        if not _https(raw.get("video_url", "")):
            raise ValueError("Meta needs a publicly reachable HTTPS video_url")
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", target.get("graph_version", "")):
            raise ValueError("Set the graph_version supported by your Meta app")
        name = target.get("token_env", "")
    else:
        name = target.get("credentials_env", "")
        if not raw.get("title") or len(raw["title"]) > 100:
            raise ValueError("YouTube needs a title of 1–100 characters")
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        raise ValueError("Credential setting must name an environment variable")
    if not isinstance(raw.get("caption", ""), str) or not isinstance(raw.get("attribution", []), list):
        raise ValueError("Caption must be text and attribution must be a list")
    credits = raw.get("attribution", [])
    if raw.get("audio_receipt"):
        receipt_path = (path.parent / raw["audio_receipt"]).resolve()
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("schema") != "taskfilm-audio-mix/v1":
            raise ValueError("Audio receipt must come from taskfilm media mix")
        audio = (receipt_path.parent / receipt["path"]).resolve()
        if not audio.is_file() or digest(audio) != receipt.get("sha256"):
            raise ValueError("Audio receipt no longer matches its recorded mix")
        credits = credits + receipt.get("attribution", [])
    if any(not isinstance(c, str) for c in credits):
        raise ValueError("Attribution entries must be text")
    credits = list(dict.fromkeys(credits))
    caption = raw.get("caption", "")
    if credits:
        caption += "\n\n" + "\n".join(credits)
    if len(caption) > (2200 if platform == "instagram" else 5000):
        raise ValueError("Caption including music credits is too long")
    scheduled = raw.get("scheduled_at")
    due = time.time()
    if scheduled:
        instant = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone")
        due = instant.timestamp()
    privacy = raw.get("privacy", "public")
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("Invalid YouTube privacy setting")
    return {**raw, "video": str(video), "video_sha256": digest(video), "caption": caption,
            "privacy": privacy, "due_at": due}


class Queue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL, due_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            checkpoint TEXT NOT NULL DEFAULT '{}', receipt TEXT, error TEXT,
            lease_until REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        self.db.commit()

    def enqueue(self, payload: dict, key: str | None = None) -> dict:
        identity = {k: payload.get(k) for k in ("video_sha256", "caption", "title", "target", "privacy",
                                               "made_for_kids", "contains_synthetic_media")}
        dedupe = key or hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        ident = hashlib.sha256(dedupe.encode()).hexdigest()[:20]
        now = time.time()
        self.db.execute("""INSERT OR IGNORE INTO posts
            (id,dedupe_key,payload,state,due_at,created_at,updated_at) VALUES (?,?,?,'queued',?,?,?)""",
            (ident, dedupe, json.dumps(payload), payload["due_at"], now, now))
        self.db.commit()
        return self.get(ident)

    def get(self, ident: str) -> dict:
        row = self.db.execute("SELECT * FROM posts WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("Unknown post ID")
        result = dict(row)
        for key in ("payload", "checkpoint", "receipt"):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def due(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        return [row[0] for row in self.db.execute(
            "SELECT id FROM posts WHERE state='queued' AND due_at<=? ORDER BY due_at,id", (now,))]

    def claim(self, ident: str, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        cursor = self.db.execute("""UPDATE posts SET state='working',lease_until=?,updated_at=?
            WHERE id=? AND state='queued' AND due_at<=?""", (now + 300, now, ident, now))
        self.db.commit()
        return self.get(ident) if cursor.rowcount else None

    def save_checkpoint(self, ident: str, checkpoint: dict):
        self.db.execute("UPDATE posts SET checkpoint=?,lease_until=?,updated_at=? WHERE id=? AND state='working'",
                        (json.dumps(checkpoint), time.time()+300, time.time(), ident))
        self.db.commit()

    def finish(self, ident: str, state: str, *, receipt=None, error=None, due_at=None, attempts=None):
        job = self.get(ident)
        self.db.execute("""UPDATE posts SET state=?,receipt=?,error=?,due_at=?,attempts=?,
            lease_until=NULL,updated_at=? WHERE id=?""",
            (state, json.dumps(receipt) if receipt else None, error,
             job["due_at"] if due_at is None else due_at,
             job["attempts"] if attempts is None else attempts, time.time(), ident))
        self.db.commit()

    def recover_expired(self, now=None):
        now = time.time() if now is None else now
        rows = self.db.execute("SELECT id,checkpoint FROM posts WHERE state='working' AND lease_until<?", (now,)).fetchall()
        for row in rows:
            pending = json.loads(row["checkpoint"]).get("pending_action")
            self.finish(row["id"], "needs_review" if pending else "queued",
                        error="Worker stopped during a provider write; reconcile before retry" if pending else None)


def _guarded(queue: Queue, job: dict, label: str, operation):
    checkpoint = job["checkpoint"]
    if checkpoint.get("pending_action"):
        raise UncertainPublication("A previous provider write has no confirmed response")
    checkpoint["pending_action"] = label
    queue.save_checkpoint(job["id"], checkpoint)
    try:
        result = operation()
    except APIError as exc:
        if exc.definitive:
            checkpoint.pop("pending_action", None)
            queue.save_checkpoint(job["id"], checkpoint)
            if exc.status in {401, 403}:
                raise ValueError("Provider credential is expired or lacks publishing permissions") from None
            raise
        # Transport/parse failures and server errors can follow a completed write.
        raise UncertainPublication(f"Unconfirmed {label}; inspect platform before retry") from None
    except Exception:
        raise UncertainPublication(f"Unconfirmed {label}; inspect platform before retry") from None
    checkpoint.pop("pending_action", None)
    checkpoint[label] = result
    queue.save_checkpoint(job["id"], checkpoint)
    return result


def _meta(queue: Queue, job: dict) -> dict:
    payload, checkpoint = job["payload"], job["checkpoint"]
    target = payload["target"]
    token = os.environ.get(target["token_env"])
    if not token:
        raise ValueError(f"Missing credential environment variable: {target['token_env']}")
    base = f"https://graph.facebook.com/{target['graph_version']}"
    headers = {"Authorization": f"Bearer {token}"}

    def call(path: str, data=None, query=None):
        url = f"{base}/{path}"
        if query:
            url += "?" + urlencode(query)
        return request_json(url, method="POST" if data is not None else "GET", data=data, headers=headers)

    if "publish" in checkpoint:
        result = checkpoint["publish"]
        remote_id = str(result.get("id") or result.get("video_id") or checkpoint.get("create", {}).get("video_id", ""))
        if target["platform"] == "facebook":
            phase = call(remote_id, query={"fields": "status"}).get("status", {}).get("publishing_phase", {}).get("status")
            if phase in {"error", "failed"}:
                raise UncertainPublication("Facebook publication failed; inspect its result")
            if phase != "complete":
                raise Waiting("Facebook is confirming publication")
        return {"platform": target["platform"], "account_id": target["account_id"], "remote_id": remote_id}
    if checkpoint.get("pending_action"):
        raise UncertainPublication("A previous Meta write needs reconciliation")
    if target["platform"] == "instagram":
        if "create" not in checkpoint:
            _guarded(queue, job, "create", lambda: call(f"{target['account_id']}/media", {
                "media_type": "REELS", "video_url": payload["video_url"], "caption": payload["caption"]}))
        creation_id = checkpoint["create"].get("id")
        if not creation_id:
            raise ValueError("Instagram did not return a container ID")
        status = call(str(creation_id), query={"fields": "status_code"}).get("status_code")
        if status in {"ERROR", "EXPIRED", "PUBLISHED"}:
            raise UncertainPublication(f"Instagram container is {status}; reconcile its result")
        if status != "FINISHED":
            raise Waiting("Instagram is processing the reel")
        result = _guarded(queue, job, "publish", lambda: call(f"{target['account_id']}/media_publish",
                                                             {"creation_id": creation_id}))
        if not result.get("id"):
            raise UncertainPublication("Instagram publish returned no media ID")
        return {"platform": "instagram", "account_id": target["account_id"], "remote_id": str(result["id"])}
    if "create" not in checkpoint:
        _guarded(queue, job, "create", lambda: call(f"{target['account_id']}/video_reels", {"upload_phase": "start"}))
    created = checkpoint["create"]
    video_id = created.get("video_id")
    if not video_id:
        raise ValueError("Facebook did not return a video ID")
    if "upload" not in checkpoint:
        upload_url = created.get("upload_url", "")
        if not _https(upload_url) or urlparse(upload_url).hostname != "rupload.facebook.com":
            raise ValueError("Facebook upload URL is outside the trusted upload host")
        _guarded(queue, job, "upload", lambda: request_json(upload_url, method="POST", headers={
            "Authorization": f"OAuth {token}", "file_url": payload["video_url"]}))
    status = call(str(video_id), query={"fields": "status"}).get("status", {})
    phases = [status.get("uploading_phase", {}).get("status"), status.get("processing_phase", {}).get("status")]
    if any(p in {"error", "failed"} for p in phases):
        raise UncertainPublication("Facebook processing failed; inspect the uploaded video")
    if phases != ["complete", "complete"]:
        raise Waiting("Facebook is processing the reel")
    result = _guarded(queue, job, "publish", lambda: call(f"{target['account_id']}/video_reels", {
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "title": payload.get("title", ""), "description": payload["caption"]}))
    if result.get("success") is not True:
        raise UncertainPublication("Facebook has not confirmed publication")
    raise Waiting("Facebook is confirming publication")


def _youtube(queue: Queue, job: dict) -> dict:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise ValueError("YouTube publishing requires pip install 'taskfilm[publish]'") from exc
    payload, checkpoint = job["payload"], job["checkpoint"]
    target = payload["target"]
    # A process can stop after the confirmed chunk is saved but before its
    # resumable/final receipt is promoted. Recover that response before sending.
    if "chunk" in checkpoint:
        chunk=checkpoint["chunk"]
        if chunk.get("response"):
            if not chunk["response"].get("id"):
                raise UncertainPublication("YouTube upload returned no video ID")
            checkpoint["publish"]=chunk["response"]
        elif chunk.get("uri"):
            checkpoint["resumable"]={"uri":chunk["uri"],"progress":chunk["progress"]}
        queue.save_checkpoint(job["id"],checkpoint)
    if "publish" in checkpoint:
        remote_id = checkpoint["publish"]["id"]
        return {"platform": "youtube", "account_id": target["account_id"],
                "remote_id": remote_id, "url": f"https://www.youtube.com/watch?v={remote_id}"}
    if checkpoint.get("pending_action"):
        raise UncertainPublication("A previous YouTube upload needs reconciliation")
    path = os.environ.get(target["credentials_env"])
    if not path or not Path(path).expanduser().is_file():
        raise ValueError(f"Missing OAuth credentials file in {target['credentials_env']}")
    credentials = Credentials.from_authorized_user_file(str(Path(path).expanduser()))
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    # Verify identity before uploading; never trust an arbitrary label in config.
    identity = service.channels().list(part="id", mine=True).execute()
    if target["account_id"] not in {str(item["id"]) for item in identity.get("items", [])}:
        raise ValueError("YouTube OAuth account does not match the configured channel")
    body = {"snippet": {"title": payload["title"], "description": payload["caption"], "categoryId": "28"},
            "status": {"privacyStatus": payload["privacy"],
                       "selfDeclaredMadeForKids": payload.get("made_for_kids", False),
                       "containsSyntheticMedia": payload.get("contains_synthetic_media", False)}}
    upload = service.videos().insert(part="snippet,status", body=body,
        media_body=MediaFileUpload(payload["video"], mimetype="video/mp4", chunksize=8*1024*1024, resumable=True))
    if "resumable" in checkpoint:
        upload.resumable_uri = checkpoint["resumable"]["uri"]
        upload.resumable_progress = checkpoint["resumable"]["progress"]
    def send_chunk():
        status, response = upload.next_chunk(num_retries=0)
        return {"response": response, "uri": upload.resumable_uri,
                "progress": getattr(status, "resumable_progress", upload.resumable_progress)}
    chunk = _guarded(queue, job, "chunk", send_chunk)
    if chunk["response"]:
        result = chunk["response"]
        if not result.get("id"):
            raise UncertainPublication("YouTube upload returned no video ID")
        checkpoint["publish"] = result
        queue.save_checkpoint(job["id"], checkpoint)
        return {"platform": "youtube", "account_id": target["account_id"],
                "remote_id": str(result["id"]), "url": f"https://www.youtube.com/watch?v={result['id']}"}
    checkpoint["resumable"] = {"uri": chunk["uri"], "progress": chunk["progress"]}
    queue.save_checkpoint(job["id"], checkpoint)
    raise Waiting("YouTube upload is continuing")


def run_job(queue: Queue, ident: str, execute: bool = False, dispatch=None) -> dict:
    if not execute:
        job = queue.get(ident)
        return {"id": ident, "state": job["state"], "dry_run": True,
                "target": job["payload"]["target"], "caption": job["payload"]["caption"]}
    job = queue.claim(ident)
    if not job:
        return {"id": ident, "skipped": True}
    try:
        video = Path(job["payload"]["video"])
        if not video.is_file() or digest(video) != job["payload"]["video_sha256"]:
            raise ValueError("Video is missing or changed after enqueue; create a new post")
        handler = dispatch or (_youtube if job["payload"]["target"]["platform"] == "youtube" else _meta)
        receipt = handler(queue, job)
        queue.finish(ident, "published", receipt={**receipt, "published_at": datetime.now(timezone.utc).isoformat()})
    except Waiting as exc:
        # Processing is not a failed attempt; bounded by age to avoid endless polls.
        if time.time() - job["created_at"] > max(3600, job["due_at"] - job["created_at"] + 3600):
            queue.finish(ident, "needs_review", error="Provider processing exceeded one hour")
        else:
            queue.finish(ident, "queued", error=str(exc), due_at=time.time()+15)
    except UncertainPublication as exc:
        queue.finish(ident, "needs_review", error=str(exc))
    except ValueError as exc:
        queue.finish(ident, "failed", error=str(exc))
    except APIError:
        attempts = job["attempts"] + 1
        queue.finish(ident, "queued" if attempts < 5 else "failed", attempts=attempts,
                     error="Provider read failed", due_at=time.time()+min(3600, 30*2**attempts))
    except Exception:
        # Do not log third-party exception strings containing credentials or URLs.
        queue.finish(ident, "needs_review", error="Unexpected provider failure; inspect before retry")
    return queue.get(ident)


def public_job(job):
    """Never emit provider upload capabilities or OAuth data to terminal logs."""
    if isinstance(job, list):
        return [public_job(item) for item in job]
    return {key: value for key, value in job.items() if key not in {"checkpoint", "payload", "dedupe_key"}}


def main(argv=None) -> int:
    default = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "taskfilm/publish.sqlite3"
    parser = argparse.ArgumentParser(prog="taskfilm publish")
    parser.add_argument("--db", type=Path, default=default)
    commands = parser.add_subparsers(dest="command", required=True)
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("manifest", type=Path)
    enqueue.add_argument("--idempotency-key")
    status = commands.add_parser("status")
    status.add_argument("id", nargs="?")
    worker = commands.add_parser("work")
    worker.add_argument("--execute", action="store_true")
    worker.add_argument("--watch", action="store_true")
    worker.add_argument("--interval", type=int, default=15)
    worker.add_argument("--limit", type=int, default=4)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("id")
    reconcile.add_argument("--remote-id", required=True)
    retry = commands.add_parser("retry")
    retry.add_argument("id")
    args = parser.parse_args(argv)
    try:
        queue = Queue(args.db)
        if args.command == "enqueue":
            result = queue.enqueue(validate_manifest(args.manifest), args.idempotency_key)
        elif args.command == "status":
            result = queue.get(args.id) if args.id else [queue.get(r[0]) for r in queue.db.execute("SELECT id FROM posts ORDER BY created_at")]
        elif args.command == "reconcile":
            job = queue.get(args.id)
            if job["state"] != "needs_review":
                raise ValueError("Reconcile is only for ambiguous posts")
            queue.finish(args.id, "published", receipt={"remote_id": args.remote_id, "reconciled": True,
                         "platform": job["payload"]["target"]["platform"],
                         "account_id": job["payload"]["target"]["account_id"]})
            result = queue.get(args.id)
        elif args.command == "retry":
            job = queue.get(args.id)
            if job["state"] != "failed" or job["checkpoint"].get("pending_action"):
                raise ValueError("Only a confirmed failed job can be retried")
            queue.finish(args.id, "queued", due_at=time.time(), attempts=0)
            result = queue.get(args.id)
        else:
            if not 1 <= args.interval <= 60 or not 1 <= args.limit <= 100:
                raise ValueError("Interval must be 1–60 seconds and limit 1–100")
            if args.watch and not args.execute:
                raise ValueError("Watch mode needs --execute; one-shot dry runs are the default")
            while True:
                if args.execute:
                    queue.recover_expired()
                result = [run_job(queue, ident, args.execute) for ident in queue.due()[:args.limit]]
                if not args.watch:
                    break
                print(json.dumps(public_job(result)), flush=True)
                time.sleep(args.interval)
        print(json.dumps(public_job(result), indent=2))
        return 0
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"taskfilm publish: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
