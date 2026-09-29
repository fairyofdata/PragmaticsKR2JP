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
