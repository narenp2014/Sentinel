from pathlib import Path

from streamlit.testing.v1 import AppTest

from sentinel_project.storage.scan_store import ScanStore


def test_assistant_screen_renders_prompt_and_read_only_response(monkeypatch):
    monkeypatch.setattr(
        ScanStore,
        "label_queue",
        lambda self, scan_id=None, **kwargs: [{
            "attempt_id": "ui-attempt",
            "scan_id": "ui-scan",
            "category": "direct_injection",
            "attempt": [{"role": "user", "content": "test prompt"}],
            "trace": {"response": "Safe refusal.", "conversation": []},
            "judge_verdict": "defended",
            "calibration": True,
        }],
    )
    monkeypatch.setattr(ScanStore, "calibration_progress", lambda self, **kwargs: {"attempts": 1, "completed": 0, "ready_for_full_sample": False})
    monkeypatch.setattr(ScanStore, "scans", lambda self: [{"scan_id": "ui-scan", "started_at": "now", "status": "completed"}])
    monkeypatch.setattr(ScanStore, "findings", lambda self, scan_id=None: [])
    app_file = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    app_test = AppTest.from_file(str(app_file)).run(timeout=20)

    assert not app_test.exception
    assert [widget.label for widget in app_test.text_area] == [
        "Question or context",
        "Assistant response",
        "Exact evidence span",
        "Reviewer notes",
    ]
    assert app_test.text_area[1].disabled
    assert app_test.toggle[0].label == "Hardened safeguards"
    assert [button.label for button in app_test.button] == [
        "Execute",
        "Start scan",
        "Prepare labeling sample",
        "Breach",
        "Defended",
        "Not delivered",
        "Ambiguous",
    ]
    assert "Human labels" in [tab.label for tab in app_test.tabs]
    assert "Judge metrics" in [tab.label for tab in app_test.tabs]