from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_assistant_screen_renders_prompt_and_read_only_response():
    app_file = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    app_test = AppTest.from_file(str(app_file)).run(timeout=20)

    assert not app_test.exception
    assert [widget.label for widget in app_test.text_area] == [
        "Question or context",
        "Assistant response",
    ]
    assert app_test.text_area[1].disabled
    assert app_test.toggle[0].label == "Hardened safeguards"
    assert [button.label for button in app_test.button] == ["Execute"]