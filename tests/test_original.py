from pathlib import Path
import time
import numpy as np
import pytest


def wait_job(runner, job, timeout=30):
    end = time.time() + timeout
    while job["status"] in ("antre", "berjalan") and time.time() < end:
        time.sleep(.03)
    assert job["status"] == "selesai", job["detail"]
    return job


def test_original_library_move_and_protect(appdata, sample):
    import services as svc
    p = sample["audio"]
    assert svc.delete_files([p], protected=[p]) == 0
    assert svc.move_files([p], "other", protected=[p]) == 0
    assert svc.move_files([p], "other") == 1
    moved = svc.list_paths("other")[0]
    assert svc.delete_files([moved]) == 1
    assert not moved.exists()


def test_original_queue_progress_lock_retry_cancel(appdata, sample):
    import services as svc
    runner = svc.JobRunner(1)
    p = sample["audio"]
    def okay(job):
        job["progress"] = .6
        return True, "ok"
    j = wait_job(runner, runner.submit("ok", okay, files=[p]))
    assert j["progress"] == 1
    calls = []
    def fail(job):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("first")
        return True, "ok"
    j = runner.submit("retry", fail)
    wait_job(runner, j) if False else None
    time.sleep(.15)
    assert j["status"] == "gagal"
    assert runner.retry_failed() == 1
    time.sleep(.15)
    assert runner.snapshot()[0]["Status"] == "selesai"
    j = runner.submit("cancel", lambda job: (True, "never"))
    runner.cancel_job(j["id"])
    time.sleep(.1)
    assert j["status"] == "dibatalkan"


def test_original_normalization_aac_and_replace(appdata, sample):
    import services as svc
    import mediatools as mt
    runner = svc.JobRunner(1)
    p = sample["audio"]
    target = mt.AudioTarget(sr=48000, ch=2, bitrate_k=160, lufs=-16, tp=-1.5, tol_lu=2)
    job = runner.submit("norm", lambda j: mt.normalize_audio(j, p, target, {"mode": "replace", "loud": "two"}, .001))
    wait_job(runner, job)
    assert p.suffix == ".m4a"
    info = svc.media_info(p)
    assert info["a"]["codec"] == "aac"
    assert info["a"]["sr"] == 48000


def test_original_opening_once_and_random_bag(appdata, sample):
    import services as svc
    s = svc.StreamManager(1)
    opening, video = sample["video"], sample["video"]
    cfg = {"v_open": [opening], "v_rand": [video], "shuffle": True}
    assert s._pick_video(cfg, [video], set())[1] == "opening"
    assert s._pick_video(cfg, [video], set())[1] == "random"
    a = [Path("a"), Path("b"), Path("c")]
    first = [s._next("test", a, True) for _ in range(3)]
    second = [s._next("test", a, True) for _ in range(3)]
    assert set(first) == set(second) == set(a)
    assert first[-1] != second[0]


def test_six_slots_isolated_logs_and_tee(appdata):
    import services as svc
    slots = [svc.StreamManager(i) for i in range(1, 7)]
    assert len({s.log_file for s in slots}) == 6
    cfg = {"rtmp_url": "rtmp://example.com/live", "stream_key": "primary-secret",
           "extra_targets": ["rtmp://example.org/live/other-secret"]}
    cmd = slots[0].build_cmd(cfg, 3, 4, 5)
    assert cmd[-3] == "-f" and cmd[-2] == "tee"
    assert "primary-secret" in cmd[-1] and "other-secret" in cmd[-1]
    slots[0].stream_key = "primary-secret"
    slots[0]._extra_keys = ["other-secret"]
    slots[0].log_file.write_text("primary-secret other-secret")
    log = slots[0].log_tail()
    assert "primary-secret" not in log and "other-secret" not in log
    with pytest.raises(ValueError):
        svc.validate_rtmp("rtmp://example.com/live/key|injection")


def test_cookie_job_is_not_retried_after_secret_cleanup(appdata):
    import services as svc
    runner = svc.JobRunner(1)
    box = svc.CookieBox("# Netscape HTTP Cookie File\n")
    job = runner.submit("cookie import", lambda j: (False, "network failed"), cleanup=box.make_releaser())
    time.sleep(.15)
    assert job["status"] == "gagal"
    assert runner.retry_failed() == 0
    assert box.write_to(appdata) is None
