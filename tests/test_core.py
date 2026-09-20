"""LLM 없이 도는 부분(검증·다수결·집계)의 테스트."""

from datetime import date

from coach.schemas import ErrorTag, GradeResult
from coach.stats import streak_days, top_types
from coach.taxonomy import codes_for_mode
from coach.lang_ja import non_error_diff
from coach.verify import merged_edits, untagged_changes
from coach.voting import combine

ANSWER = "昨日友達を合いました。"
FIXED = "昨日友達に会いました。"
GRAMMAR = codes_for_mode("grammar")


def tag(type_, original, corrected):
    return ErrorTag(type=type_, severity="error", original=original, corrected=corrected,
                    kr_interference=False, explanation_ko="")


def result(tags, correction=FIXED):
    return GradeResult(intended_meaning_ko="", minimal_correction=correction,
                       natural_version=correction, errors=tags)


# ---- 검증 E: 태그 없이 고친 곳 ----

def test_untagged_change_is_detected():
    tags = [tag("PARTICLE", "を", "に")]          # 合→会 는 태그 없이 고침
    missing = untagged_changes(ANSWER, FIXED, tags)
    assert missing == [{"original": "合", "corrected": "会"}]


def test_all_changes_tagged():
    tags = [tag("PARTICLE", "を", "に"), tag("ORTHOGRAPHY", "合い", "会い")]
    assert untagged_changes(ANSWER, FIXED, tags) == []


def test_insertion_next_to_tag_is_covered():
    # 조사 누락: 앞 단어를 포함해 인용하면 삽입 지점이 덮인다
    answer, fixed = "東京行きます", "東京に行きます"
    assert untagged_changes(answer, fixed, [tag("PARTICLE", "東京", "東京に")]) == []


# ---- 검증 D + 다수결 ----

def test_quote_not_in_answer_is_dropped():
    # LLM 이 이미 고친 형태(に)로 인용 → 원문에 없으므로 버린다
    samples = [result([tag("PARTICLE", "友達に", "友達に")])]
    out = combine(ANSWER, samples, GRAMMAR)
    assert out["errors"] == [] and out["dropped_quotes"] == 1


def test_majority_vote():
    particle = tag("PARTICLE", "を", "に")
    particle_wide = tag("PARTICLE", "友達を", "友達に")   # 범위가 달라도 겹치면 같은 지적
    ortho = tag("ORTHOGRAPHY", "合", "会")
    samples = [result([particle, ortho]), result([particle_wide]), result([particle])]
    out = combine(ANSWER, samples, GRAMMAR)
    assert [(e.type, e.votes) for e in out["errors"]] == [("PARTICLE", 3)]
    assert [(e.type, e.votes) for e in out["tentative_errors"]] == [("ORTHOGRAPHY", 1)]


def test_type_outside_mode_is_dropped():
    samples = [result([tag("REGISTER", "を", "に")])]    # 표현 모드 유형을 문법 모드에서
    assert combine(ANSWER, samples, GRAMMAR)["dropped_quotes"] == 1


# ---- 전각/반각, 합침 검출 ----

def test_width_only_tag_is_dropped_and_not_untagged():
    answer, fixed = "了解です!", "了解です！"
    out = combine(answer, [result([tag("ORTHOGRAPHY", "!", "！")], fixed)], GRAMMAR)
    assert out["errors"] == [] and out["dropped_width"] == 1
    assert out["untagged_changes"] == []


def test_merged_tag_is_reported():
    samples = [result([tag("PARTICLE", "友達を合って", "友達に会って")])] * 3
    out = combine("昨日友達を合って帰りました。", samples, GRAMMAR)
    assert out["merged_tags"][0]["edits"] == [{"original": "友達を", "corrected": "友達に"},
                                              {"original": "合って", "corrected": "会って"}]


def test_merged_tag_without_kanji_change():
    # 한자가 바뀌지 않아도 서로 다른 두 단어가 고쳐졌으면 경고한다
    assert len(merged_edits("駅を書けた", "駅に書いた")) == 2


def test_half_width_katakana_is_a_real_error():
    # 폭 차이라고 뭉뚱그리면 안 되는 표기 오류
    assert not non_error_diff("ｻｰﾊﾞｰ", "サーバー")
    assert non_error_diff("！", "!") and non_error_diff("　", " ")


def test_merged_warning_skipped_when_other_tag_covers_it():
    tags = [tag("PARTICLE", "友達を合い", "友達に会い"), tag("ORTHOGRAPHY", "合い", "会い")]
    out = combine(ANSWER, [result(tags)] * 3, GRAMMAR)
    assert out["merged_tags"] == []


def test_okurigana_and_keigo_are_not_merged():
    for a, b in [("薬を食べて", "薬を飲んで"), ("連絡しました", "ご連絡いたしました")]:
        assert merged_edits(a, b) == []


# ---- 집계 ----

def record(ts, types):
    return {"timestamp": ts, "answer": "a", "topic": "t", "mode": "grammar",
            "taxonomy_version": "v0", "tentative_errors": [], "untagged_changes": [],
            "errors": [{"type": t, "original": "x", "corrected": "y", "explanation_ko": "",
                        "severity": "error", "kr_interference": False} for t in types]}


def test_top_types_counts_attempts_not_occurrences():
    records = [
        record("2026-09-20T10:00:00+09:00", ["CONJUGATION"] * 5),  # 한 시도에 5번
        record("2026-09-20T11:00:00+09:00", ["PARTICLE"]),
        record("2026-09-20T12:00:00+09:00", ["PARTICLE", "OUT_OF_MODE"]),
    ]
    ranked = top_types(records)
    assert [(r["code"], r["attempts_with"], r["count"]) for r in ranked] == [
        ("PARTICLE", 2, 2), ("CONJUGATION", 1, 5)]


def test_top_types_is_deterministic_on_ties():
    records = [record("2026-09-20T10:00:00+09:00", ["VOICE", "CONNECTIVE"])]
    assert [r["code"] for r in top_types(records)] == ["CONNECTIVE", "VOICE"]


def test_streak():
    recs = [record(f"2026-09-{d}T10:00:00+09:00", []) for d in (17, 18, 19)]
    assert streak_days(recs, today=date(2026, 9, 20)) == 3   # 오늘 아직 안 해도 유지
    assert streak_days(recs, today=date(2026, 9, 21)) == 0
