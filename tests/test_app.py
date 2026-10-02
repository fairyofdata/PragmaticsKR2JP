"""화면이 오류 없이 뜨는지 확인한다 (API 호출 없음).

AppTest = Streamlit 이 제공하는 테스트 도구. 브라우저 없이 app.py 를 실행하고 위젯을 눌러 볼 수 있다.
기록 폴더는 테스트마다 임시 폴더로 돌려서 실제 data/ 를 건드리지 않는다.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from coach import store

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def temp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_FILE", tmp_path / "attempts.jsonl")
    monkeypatch.delenv("COACH_PASSCODE", raising=False)


def run():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_app_starts_and_shows_summary_with_demo_samples():
    at = run()
    at.sidebar.toggle[0].set_value(True).run()            # 이전 버전 기록 포함 (시연 예시는 p1)
    assert not at.exception
    headers = [m.value for m in at.markdown if m.value.startswith("###")]
    assert "### 빈출 오답" in headers and "### 자주 틀리는 유형 상위 5개" in headers


def test_every_mode_and_input_kind_renders():
    at = run()
    for mode in ("grammar", "expression"):
        at.segmented_control(key="mode").set_value(mode).run()
        for kind in ("generated", "own_korean", "targeted"):
            at.segmented_control(key="input_kind").set_value(kind).run()
            assert not at.exception, (mode, kind, [e.value for e in at.exception])


def test_mode_control_is_in_the_page_body_for_phones():
    at = run()
    assert at.segmented_control(key="mode") is not None
    assert all(r.label != "모드" for r in at.sidebar.radio)   # 폰에서는 사이드바가 접혀 있다


def test_passcode_locks_the_app(monkeypatch):
    monkeypatch.setenv("COACH_PASSCODE", "open-sesame")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 0            # 암호 전에는 아무것도 안 보인다
    at.text_input[0].input("wrong").run()
    assert [e.value for e in at.error] == ["암호가 다릅니다."] and len(at.tabs) == 0
    at.text_input[0].input("open-sesame").run()
    assert not at.exception and len(at.tabs) == 2            # 연습 / 요약
