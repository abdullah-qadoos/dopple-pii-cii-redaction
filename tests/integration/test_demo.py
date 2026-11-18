from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "src" / "piiredact" / "app" / "streamlit_app.py"


def test_demo_renders_and_redacts_sample() -> None:
    at = AppTest.from_file(str(APP), default_timeout=300).run()
    assert not at.exception
    after = at.text[0].value  # the "After" pane
    assert "4111 1111 1111 1111" not in after
    assert "leah.whitfield@" not in after
    assert at.dataframe  # findings table rendered
