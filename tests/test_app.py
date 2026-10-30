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
        for kind in ("generated", "own_korean", "own_japanese", "targeted"):
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


def fake_grade(*args, **kwargs):
    from coach.schemas import Attempt, VotedTag
    tag = VotedTag(type="PARTICLE", severity="error", original="を", corrected="に", kr_interference=True,
                   explanation_ko="", votes=3, start=3, end=4)
    return Attempt(id="t1", timestamp="2026-10-07T10:00:00+09:00", source="app", mode="grammar", topic=args[3],
                   medium=args[4], relationship=args[5], task=args[1], input_mode=kwargs["input_mode"],
                   duration_sec=kwargs["duration_sec"], answer=args[0], intended_meaning_ko="친구를 만났다.",
                   minimal_correction=" 友達に会った。", natural_version="友達に会ったよ。", errors=[tag],
                   tentative_errors=[], untagged_changes=[], dropped_quotes=0,
                   confirmed_correction=" 友達に会った。", correction_source="confirmed_tags", n_samples=3,
                   taxonomy_version="v1", prompt_version="p2", schema_version="s5", model="m",
                   thinking_level="low", usage={})


def test_own_japanese_is_graded_as_pasted_and_contrast_is_shown(monkeypatch):
    from coach import llm
    monkeypatch.setattr(llm, "grade", fake_grade)
    monkeypatch.setattr(llm, "register_contrast", lambda *a: ({
        "relationships": ["사내 상사", "친한 친구"], "texts": ["友人に会いました。", "友達に会ったよ。"],
        "points": [{"aspect_ko": "문말", "forms": ["会いました", "会ったよ"], "explanation_ko": "설명",
                    "spans": [(3, 8), (3, 7)]}],
        "dropped_points": 0, "base_relationship": "친한 친구"}, {}))
    at = run()
    at.segmented_control(key="input_kind").set_value("own_japanese").run()
    at.text_area(key="own_ja_input").input(" 友達を会った。").run()
    next(b for b in at.button if b.label.startswith("채점")).click().run()
    assert not at.exception, [e.value for e in at.exception]

    saved = store.load(store.DATA_FILE)
    assert len(saved) == 1
    assert saved[0]["answer"] == " 友達を会った。"                    # 원문 그대로 (앞 공백도)
    assert (saved[0]["input_mode"], saved[0]["duration_sec"]) == ("own_japanese", None)
    assert not any(t.label == "일본어로 쓰기" for t in at.text_area)   # 답 입력란을 다시 띄우지 않는다

    next(b for b in at.button if b.label.startswith("상대를 바꿔 보기")).click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("(이번 장면)" in m.value for m in at.markdown)
    assert len(store.load(store.DATA_FILE)) == 1                       # 대비는 기록에 넣지 않는다
