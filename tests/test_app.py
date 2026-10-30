from pathlib import Path
import os
import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def fresh_app(timeout=30):
    import streamlit as st
    import services as svc
    st.cache_resource.clear()
    st.cache_data.clear()
    svc.STREAM_INSTANCES.clear()
    return AppTest.from_file(str(ROOT/"app.py"), default_timeout=timeout)


def test_all_original_and_new_tabs_no_exceptions(appdata):
    at = fresh_app().run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [t.label for t in at.tabs]
    for expected in ("📁 Library", "⬇️ Impor", "🧰 Normalisasi & Tes", "🔴 Live 24 Jam", "⚙️ Job", "🎨 Clipdrop → Video", "📱 Viral Shorts"):
        assert expected in labels
    assert at.session_state["_creative_runner"] is not None


def test_shorts_modes_and_six_slot_selector(appdata, sample):
    at = fresh_app().run()
    at.radio(key="shorts_mode").set_value("B · Reaction Warga +62").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.label == "Render Reaction Shorts → MP4" for b in at.button)
    at.radio(key="shorts_mode").set_value("Kirim / Upload hasil").run()
    assert not at.exception, [e.value for e in at.exception]
    at.selectbox(key="live_selected_slot").set_value(6).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.key == "l_start_6" for b in at.button)
    assert len(__import__("services").STREAM_INSTANCES) == 6


def test_password_gate(appdata, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-admin-password")
    at = fresh_app().run()
    assert not at.exception
    assert not at.tabs
    at.text_input[0].input("test-admin-password")
    at.form_submit_button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["authenticated"] is True


def test_clipdrop_query_is_cleared_and_never_enters_job(appdata, monkeypatch):
    from extensions import clipdrop, jobs
    seen = []
    def image(prompt, key):
        assert key == "browser-only-key"
        p = appdata/"tmp"/"generated.png"
        from PIL import Image
        Image.new("RGB", (16, 16), "white").save(p)
        return p
    def submit(runner, kind, payload, title=None):
        seen.append(payload)
        assert "browser-only-key" not in repr(payload)
        return {"id": "test-job"}
    monkeypatch.setattr(clipdrop, "generate", image)
    monkeypatch.setattr(jobs, "submit_creative", submit)
    at = fresh_app()
    at.query_params.update({"cdk":"browser-only-key", "cd_prompt":"test", "cd_effect":"rain", "cd_duration":"5", "cd_nonce":"once-only"})
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "cdk" not in at.query_params
    assert "browser-only-key" not in repr(dict(at.session_state))
    assert len(seen) == 1
    at.run()
    assert len(seen) == 1


def test_light_theme_and_uploader_light():
    import tomllib
    theme = tomllib.loads((ROOT/".streamlit/config.toml").read_text())["theme"]
    assert theme["base"] == "light" and theme["backgroundColor"] == "#FFFFFF"
    import uploader
    assert "color-scheme:light" in uploader.PAGE
    assert "prefers-color-scheme:dark" not in uploader.PAGE


def test_manual_live_start_uses_original_engine_without_duplicate_widgets(appdata, sample, monkeypatch):
    import services as svc
    calls = []
    monkeypatch.setattr(svc.StreamManager, "start", lambda self,cfg,hours: calls.append((self.slot,cfg,hours)))
    at = fresh_app().run()
    at.selectbox(key="live_selected_slot").set_value(2).run()
    at.multiselect(key="l_rand_2").set_value([sample["video"]]).run()
    at.multiselect(key="l_arand_2").set_value([sample["audio"]]).run()
    at.text_input(key="l_key_2").input("test-key").run()
    at.button(key="l_start_2").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert calls and calls[0][0] == 2
    assert list(map(str,calls[0][1]["v_rand"])) == [str(sample["video"])]
    assert list(map(str,calls[0][1]["a_rand"])) == [str(sample["audio"])]
