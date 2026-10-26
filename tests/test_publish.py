import json
import time

import pytest

from taskfilm import publish


@pytest.fixture
def payload(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"a frozen, reviewed test artifact")
    return {"video": str(video), "video_sha256": publish.digest(video), "caption": "A useful product",
            "title": "Product demo", "due_at": time.time()-1, "privacy": "public",
            "target": {"platform": "instagram", "account_id": "12345", "token_env": "TEST_META_TOKEN",
                       "graph_version": "v26.0"}, "video_url": "https://example.com/ad.mp4"}


def test_enqueue_and_retry_do_not_duplicate_published_posts(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    first = queue.enqueue(payload)
    second = queue.enqueue(payload)
    assert first["id"] == second["id"]
    calls = []
    def handler(queue, job):
        calls.append(job["id"])
        return {"remote_id": "real-response-id"}
    assert publish.run_job(queue, first["id"], True, handler)["state"] == "published"
    assert publish.run_job(queue, first["id"], True, handler)["skipped"]
    assert calls == [first["id"]]


def test_worker_preview_never_calls_a_provider(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    def forbidden(*args):
        pytest.fail("Dry run called a publishing provider")
    result = publish.run_job(queue, job["id"], False, forbidden)
    assert result["dry_run"] and queue.get(job["id"])["state"] == "queued"


def test_only_one_worker_can_claim_a_post(tmp_path, payload):
    path = tmp_path / "posts.sqlite3"
    one, two = publish.Queue(path), publish.Queue(path)
    job = one.enqueue(payload)
    assert one.claim(job["id"])
    assert two.claim(job["id"]) is None


def test_future_posts_wait_until_their_schedule(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    now = time.time()
    job = queue.enqueue({**payload, "due_at": now+3600})
    assert queue.due(now) == []
    assert queue.claim(job["id"], now) is None
    assert queue.due(now+3601) == [job["id"]]


def test_ambiguous_publish_response_is_not_retried(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    calls = []
    def handler(queue, job):
        def send():
            calls.append("send")
            raise publish.APIError("lost response")
        return publish._guarded(queue, job, "publish", send)
    result = publish.run_job(queue, job["id"], True, handler)
    assert result["state"] == "needs_review"
    assert result["checkpoint"]["pending_action"] == "publish"
    assert queue.due() == []
    assert publish.run_job(queue, job["id"], True, handler)["skipped"]
    assert calls == ["send"]


def test_crashed_write_lease_requires_reconciliation(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    claimed = queue.claim(job["id"])
    queue.save_checkpoint(job["id"], {"pending_action": "publish", "create": {"id": "container"}})
    queue.recover_expired(time.time()+400)
    assert queue.get(job["id"])["state"] == "needs_review"


def test_asset_changes_after_enqueue_fail_before_upload(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    from pathlib import Path
    Path(payload["video"]).write_bytes(b"different ad")
    result = publish.run_job(queue, job["id"], True, lambda *a: pytest.fail("Unexpected upload"))
    assert result["state"] == "failed"


def test_instagram_processing_reuses_container_and_publishes_once(tmp_path, payload, monkeypatch):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    monkeypatch.setenv("TEST_META_TOKEN", "test-only-placeholder")
    calls = []
    answers = [{"id": "container-1"}, {"status_code": "IN_PROGRESS"},
               {"status_code": "FINISHED"}, {"id": "published-1"}]
    def request(url, **kwargs):
        calls.append(url)
        return answers.pop(0)
    monkeypatch.setattr(publish, "request_json", request)
    first = publish.run_job(queue, job["id"], True)
    assert first["state"] == "queued" and first["attempts"] == 0
    assert first["checkpoint"]["create"]["id"] == "container-1"
    queue.db.execute("UPDATE posts SET due_at=? WHERE id=?", (time.time()-1, job["id"]))
    queue.db.commit()
    result = publish.run_job(queue, job["id"], True)
    assert result["state"] == "published" and result["receipt"]["remote_id"] == "published-1"
    assert sum(url.endswith("/media") for url in calls) == 1
    assert sum(url.endswith("/media_publish") for url in calls) == 1


def test_caption_keeps_music_attribution_and_credentials_are_references(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(publish, "probe", lambda path: {"streams": [{"codec_type": "video"}]})
    manifest = tmp_path / "post.json"
    raw = {"schema": "taskfilm-publish/v1", "video": payload["video"], "caption": "Try it",
           "video_url": payload["video_url"], "target": payload["target"], "attribution": ["Music credit"]}
    manifest.write_text(json.dumps(raw))
    parsed = publish.validate_manifest(manifest)
    assert parsed["caption"] == "Try it\n\nMusic credit"
    raw["target"]["access_token"] = "never-accepted"
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="not secrets"):
        publish.validate_manifest(manifest)


def test_terminal_status_redacts_upload_capabilities():
    output = publish.public_job({"id": "job", "checkpoint": {"uri": "private-upload-url"},
                                 "payload": {"video_url": "signed-url"}, "state": "queued"})
    assert output == {"id": "job", "state": "queued"}


def test_mix_receipt_carries_verified_music_credit_into_post(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(publish, "probe", lambda path: {"streams": [{"codec_type": "video"}]})
    audio=tmp_path/'mix.wav'
    audio.write_bytes(b'original audio mix')
    receipt=tmp_path/'mix.mix.json'
    receipt.write_text(json.dumps({'schema':'taskfilm-audio-mix/v1','path':'mix.wav',
                                  'sha256':publish.digest(audio),'attribution':['Artist credit']}))
    manifest=tmp_path/'post.json'
    manifest.write_text(json.dumps({'schema':'taskfilm-publish/v1','video':payload['video'],
        'video_url':payload['video_url'],'target':payload['target'],'caption':'Try it',
        'audio_receipt':'mix.mix.json','attribution':['Artist credit']}))
    assert publish.validate_manifest(manifest)['caption']=='Try it\n\nArtist credit'
    audio.write_bytes(b'changed mix')
    with pytest.raises(ValueError,match='no longer matches'):
        publish.validate_manifest(manifest)


def test_expired_credentials_are_a_confirmed_failure(tmp_path, payload):
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    def handler(queue, job):
        def rejected():
            raise publish.APIError("rejected", status=401, definitive=True)
        return publish._guarded(queue, job, "publish", rejected)
    result = publish.run_job(queue, job["id"], True, handler)
    assert result["state"] == "failed"
    assert "pending_action" not in result["checkpoint"]


def test_facebook_waits_for_actual_publication_confirmation(tmp_path, payload, monkeypatch):
    payload["target"]["platform"] = "facebook"
    queue = publish.Queue(tmp_path / "posts.sqlite3")
    job = queue.enqueue(payload)
    monkeypatch.setenv("TEST_META_TOKEN", "test-only-placeholder")
    answers = [{"video_id": "video-1", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/video-1"},
               {"success": True}, {"status": {"uploading_phase": {"status": "complete"},
                "processing_phase": {"status": "complete"}}}, {"success": True},
               {"status": {"publishing_phase": {"status": "complete"}}}]
    calls=[]
    def request(url, **kwargs):
        calls.append((url, kwargs.get("data")))
        return answers.pop(0)
    monkeypatch.setattr(publish, "request_json", request)
    assert publish.run_job(queue, job["id"], True)["state"] == "queued"
    queue.db.execute("UPDATE posts SET due_at=? WHERE id=?", (time.time()-1, job["id"]))
    queue.db.commit()
    result=publish.run_job(queue, job["id"], True)
    assert result["state"] == "published"
    assert result["receipt"]["remote_id"] == "video-1"
    assert sum(bool(data and data.get("upload_phase")=="finish") for url,data in calls) == 1


def test_youtube_recovers_confirmed_final_chunk_without_second_upload(tmp_path,payload,monkeypatch):
    pytest.importorskip('googleapiclient')
    from googleapiclient import discovery
    monkeypatch.setattr(discovery,'build',lambda *a,**kw:pytest.fail('Started second upload'))
    payload['target']={'platform':'youtube','account_id':'channel','credentials_env':'TEST_YT_OAUTH'}
    queue=publish.Queue(tmp_path/'posts.sqlite3')
    job=queue.enqueue(payload)
    queue.db.execute('UPDATE posts SET checkpoint=? WHERE id=?',
        (json.dumps({'chunk':{'response':{'id':'confirmed-video'},'uri':'upload-capability','progress':100}}),job['id']))
    queue.db.commit()
    result=publish.run_job(queue,job['id'],True)
    assert result['state']=='published'
    assert result['receipt']['remote_id']=='confirmed-video'
