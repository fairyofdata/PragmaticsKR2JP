"""llm.grade 가 기록 형식을 제대로 채우는지. 실제 API 대신 가짜 채점 결과를 넣는다 (monkeypatch = 테스트 동안만 함수 바꿔치기)."""

from coach import llm
from coach.schemas import SCHEMA_VERSION, ErrorTag, GradeResult


def test_grade_records_own_korean_fields(monkeypatch):
    fake = GradeResult(intended_meaning_ko="", minimal_correction="友達に会った。", natural_version="",
                       errors=[ErrorTag(type="PARTICLE", severity="error", original="を", corrected="に",
                                        kr_interference=True, explanation_ko="")])
    monkeypatch.setattr(llm, "grade_samples", lambda prompt, mode, n: ([fake] * n, {}))

    task = llm.own_korean_task("친구를 만났다.", "채팅", "친한 친구")
    attempt = llm.grade("友達を会った。", task, "grammar", "내 문장", "채팅", "친한 친구",
                        input_mode="own_korean", source_ko="친구를 만났다.", duration_sec=42)

    assert (attempt.input_mode, attempt.source_ko, attempt.duration_sec) == ("own_korean", "친구를 만났다.", 42)
    assert attempt.schema_version == SCHEMA_VERSION
    assert attempt.confirmed_correction == "友達に会った。"
    assert "친구를 만났다." in attempt.task.situation_ko


def test_own_japanese_task_has_no_korean_source_and_keeps_context():
    task = llm.own_japanese_task("회의 일정 변경을 부탁", "메일", "사내 상사")
    assert "회의 일정 변경을 부탁" in task.situation_ko and "사내 상사" in task.instruction_ko
    assert "쓴 상황" not in llm.own_japanese_task("", "메일", "사내 상사").situation_ko


def test_register_contrast_uses_requested_relationships_and_checks_quotes(monkeypatch):
    import json
    from coach.prompts import CONTRAST_RELATIONSHIPS
    texts = ["ご確認いただけますでしょうか。", "ご確認いただけますか。", "確認お願いします。", "確認して。"]
    reply = {"variants": [{"relationship": "아무 이름", "text": t} for t in texts],
             "points": [{"aspect_ko": "의뢰", "explanation_ko": "",
                         "forms": ["いただけますでしょうか", "いただけますか", "お願いします", "して"]},
                        {"aspect_ko": "없는 인용", "explanation_ko": "",
                         "forms": ["くださいませ", "いただけますか", "お願いします", "して"]}]}
    monkeypatch.setattr(llm, "_call", lambda *a: (json.dumps(reply), {"input_tokens": 1}))
    contrast, usage = llm.register_contrast("확인해 주세요", "確認お願いします。", "채팅", "사내 동료")
    assert contrast["relationships"] == CONTRAST_RELATIONSHIPS and contrast["texts"] == texts
    assert [p["aspect_ko"] for p in contrast["points"]] == ["의뢰"] and contrast["dropped_points"] == 1
    assert contrast["points"][0]["spans"][3] == (2, 4)
