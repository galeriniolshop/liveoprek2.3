"""Verify tones in the FINAL encoded output, including RANDOM without LOOP.

This follows the supplied live-audio-mix.md: checking feeders alone is insufficient.
"""
from pathlib import Path
import subprocess
import time
import numpy as np
import pytest


def tone(path, frequency, seconds=8):
    from extensions import media
    media.ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=44100", "-t", str(seconds),
                  "-c:a", "aac", str(path)])


def peak_near(output, frequency):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(output), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"])
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    assert len(x) > 16000, "output audio too short"
    x = x[16000:16000*4]
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1/16000)
    signal = power[(freqs > frequency-30) & (freqs < frequency+30)].max()
    noise = np.median(power[(freqs > 100) & (freqs < 7000)]) + 1e-12
    return float(signal/noise)


def run_live(appdata, sample, with_loop, silence=False):
    import services as svc
    loop, random = appdata/"loop.m4a", appdata/"random.m4a"
    tone(loop, 440)
    tone(random, 1000)
    output = appdata/("mixed.flv" if with_loop else "silent.flv" if silence else "random.flv")
    stream = svc.StreamManager(2 if with_loop else 4 if silence else 3)
    cfg = {"videos": [sample["video"]], "audios": ([loop] if with_loop else []) + ([] if silence else [random]),
           "v_open": [], "v_rand": [sample["video"]], "a_loop": [loop] if with_loop else [],
           "a_rand": [] if silence else [random], "rtmp_url": "rtmp://unused.local/live", "stream_key": "unused",
           "_output": str(output), "height": 480, "fps": 24, "vmode": "normalize", "vbr_k": 800,
           "vol_loop": .65, "vol_rand": .85, "allow_silence": silence, "disk_min_gb": .001}
    stream.start(cfg, .004)
    deadline = time.time()+25
    while stream.running and stream.state != "live" and time.time() < deadline:
        time.sleep(.1)
    assert stream.state == "live", stream.detail + "\n" + stream.log_tail()
    time.sleep(5)
    stream.stop()
    deadline = time.time()+15
    while stream.running and time.time() < deadline:
        time.sleep(.1)
    assert not stream.running
    assert output.exists() and output.stat().st_size > 10000
    return output


def test_final_encoded_loop_and_random_are_both_audible(appdata, sample):
    output = run_live(appdata, sample, True)
    assert peak_near(output, 440) > 100
    assert peak_near(output, 1000) > 100


def test_final_encoded_random_alone_and_silence_fallback(appdata, sample):
    output = run_live(appdata, sample, False)
    assert peak_near(output, 1000) > 100
    assert peak_near(output, 440) < 20
    # The no-music path must keep a real PCM input rather than dropping the audio stream.
    silent = run_live(appdata, sample, False, True)
    from extensions import media
    assert media.has_audio(silent)


def test_real_rtmp_simulcast_two_destinations(appdata, sample):
    import services as svc
    from extensions import media
    outputs = [appdata/"rtmp-one.flv", appdata/"rtmp-two.flv"]
    receivers = []
    stream = svc.StreamManager(5)
    try:
        for port, output in zip((19351, 19352), outputs):
            p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-listen", "1", "-i",
                                  f"rtmp://127.0.0.1:{port}/live/test", "-t", "8", "-c", "copy", "-f", "flv", str(output)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            receivers.append(p)
        time.sleep(.5)
        cfg = {"videos":[sample["video"]], "audios":[sample["audio"]], "v_open":[], "v_rand":[sample["video"]],
               "a_loop":[], "a_rand":[sample["audio"]], "rtmp_url":"rtmp://127.0.0.1:19351/live", "stream_key":"test",
               "extra_targets":["rtmp://127.0.0.1:19352/live/test"], "height":480, "fps":24,
               "vmode":"normalize", "vbr_k":800, "disk_min_gb":.001}
        stream.start(cfg, .003)
        time.sleep(9)
        stream.stop()
        end=time.time()+15
        while stream.running and time.time()<end:
            time.sleep(.1)
        for p in receivers:
            if p.poll() is None:
                p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for output in outputs:
            assert output.exists() and output.stat().st_size > 10000, stream.log_tail()
            assert media.has_audio(output)
            assert any(s["codec_type"] == "video" for s in media.probe(output)["streams"])
    finally:
        stream.stop()
        for p in receivers:
            if p.poll() is None:
                p.kill()
            p.stdout.close(); p.stderr.close()


def test_six_real_encoder_processes_are_independent(appdata, sample):
    import services as svc
    from extensions import media
    streams = [svc.StreamManager(slot) for slot in range(1, 7)]
    try:
        for slot, stream in enumerate(streams, 1):
            cfg = {"videos":[sample["video"]], "audios":[sample["audio"]], "v_open":[], "v_rand":[sample["video"]],
                   "a_loop":[sample["audio"]] if slot % 2 else [], "a_rand":[sample["audio"]],
                   "rtmp_url":"", "stream_key":"", "_output":str(appdata/f"six-{slot}.mp4"),
                   "height":480, "fps":24, "vmode":"normalize", "vbr_k":600, "disk_min_gb":.001}
            stream.start(cfg, .02)
        end=time.time()+45
        while any(s.running and s.state != "live" for s in streams) and time.time()<end:
            time.sleep(.2)
        assert all(s.state == "live" for s in streams), [(s.slot,s.state,s.detail,s.log_tail()) for s in streams]
        time.sleep(5)
        for stream in streams:
            stream.stop()
        end=time.time()+20
        while any(s.running for s in streams) and time.time()<end:
            time.sleep(.2)
        assert not any(s.running for s in streams), [(s.slot,s.log_tail()) for s in streams]
        for slot in range(1,7):
            path=appdata/f"six-{slot}.mp4"
            assert path.is_file() and path.stat().st_size>1000, (slot, streams[slot-1].log_tail())
            info=media.probe(path)
            assert media.has_audio(path)
            assert 4.5 <= float(info["format"]["duration"]) <= 12, (slot, streams[slot-1].log_tail())
            assert any(s["codec_name"]=="h264" for s in info["streams"])
    finally:
        for s in streams:
            s.stop()
