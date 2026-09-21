"""LLM 없이 도는 부분(검증·다수결·집계)의 테스트."""

from datetime import date

from coach.schemas import ErrorTag, GradeResult, VotedTag
from coach.stats import filter_records, streak_days, top_types
from coach.taxonomy import codes_for_mode
from coach.lang_ja import non_error_diff
from coach.verify import apply_tags, find_span, merged_edits, untagged_changes
from coach.voting import combine

ANSWER = "昨日友達を合いました。"
FIXED = "昨日友達に会いました。"
GRAMMAR = codes_for_mode("grammar")


def tag(type_, original, corrected):
    return ErrorTag(type=type_, severity="error", original=original, corrected=corrected,
                    kr_interference=False, explanation_ko="")


def spans(answer, *originals):
    return [find_span(answer, o) for o in originals]


def result(tags, correction=FIXED):
    return GradeResult(intended_meaning_ko="", minimal_correction=correction,
                       natural_version=correction, errors=tags)


# ---- 검증 E: 태그 없이 고친 곳 ----

def test_untagged_change_is_detected():
    missing = untagged_changes(ANSWER, FIXED, spans(ANSWER, "を"))   # 合→会 는 태그 없이 고침
    assert missing == [{"original": "合", "corrected": "会"}]


def test_all_changes_tagged():
    assert untagged_changes(ANSWER, FIXED, spans(ANSWER, "を", "合い")) == []


def test_insertion_next_to_tag_is_covered():
    # 조사 누락: 앞 단어를 포함해 인용하면 삽입 지점이 덮인다
    answer, fixed = "東京行きます", "東京に行きます"
    assert untagged_changes(answer, fixed, spans(answer, "東京")) == []


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


# ---- 같은 인용이 답에 여러 번 나올 때 (외부 리뷰 1번) ----

DUP_ANSWER = "友達を会って、映画を見るを好きです。"
DUP_FIXED = "友達に会って、映画を見るのが好きです。"


def test_same_quote_twice_keeps_both_errors():
    # 「を」가 세 번 나온다. 첫 번째(→に)와 세 번째(→のが)가 서로 다른 오류다.
    tags = [tag("PARTICLE", "を", "に"), tag("PARTICLE", "を", "のが")]
    out = combine(DUP_ANSWER, [result(tags, DUP_FIXED)] * 3, GRAMMAR)
    assert len(out["errors"]) == 2
    assert sorted((e.start, e.corrected) for e in out["errors"]) == [(2, "に"), (12, "のが")]


def test_untagged_change_not_hidden_by_same_quote_elsewhere():
    # 첫 번째 「を」만 태그했는데, 세 번째 「を」도 고쳐졌다 → 그건 태그 없는 수정으로 드러나야 한다
    out = combine(DUP_ANSWER, [result([tag("PARTICLE", "を", "に")], DUP_FIXED)], GRAMMAR)
    assert out["untagged_changes"] == [{"original": "を", "corrected": "のが"}]


def ctx_tag(original, corrected, before, after=""):
    t = tag("PARTICLE", original, corrected)
    return t.model_copy(update={"context_before": before, "context_after": after})


def test_context_picks_the_right_occurrence():
    # 두 「を」가 똑같이 →に 로 고쳐져서 교정문만으로는 구별할 수 없다 → 문맥(앞 글자)으로 정한다
    answer, fixed = "駅を着いて、家を着いた。", "駅に着いて、家に着いた。"
    tags = [ctx_tag("を", "に", "家"), ctx_tag("を", "に", "駅")]
    out = combine(answer, [result(tags, fixed)] * 3, GRAMMAR)
    assert sorted(e.start for e in out["errors"]) == [1, 7]
    assert out["ambiguous_quotes"] == 0


def test_ambiguous_quote_is_reported():
    # 문맥도 없고 교정도 똑같으면 위치를 하나로 못 정한다 → 모호로 드러낸다
    answer, fixed = "駅を着いて、家を着いた。", "駅に着いて、家に着いた。"
    out = combine(answer, [result([tag("PARTICLE", "を", "に")], fixed)], GRAMMAR)
    assert out["ambiguous_quotes"] == 1


# ---- 확정 태그로 만든 교정문 (외부 리뷰 3번) ----

def test_confirmed_correction_uses_only_confirmed_tags():
    # 3번 중 1번만 나온 ORTHOGRAPHY(合→会)는 확정이 아니므로 교정문에 들어가지 않는다
    particle, ortho = tag("PARTICLE", "を", "に"), tag("ORTHOGRAPHY", "合", "会")
    samples = [result([particle, ortho]), result([particle]), result([particle])]
    out = combine(ANSWER, samples, GRAMMAR)
    assert out["confirmed_correction"] == "昨日友達に合いました。"
    assert out["correction_source"] == "confirmed_tags"


def test_apply_tags_nested_and_conflict():
    outer = VotedTag(**tag("PARTICLE", "友達を合い", "友達に会い").model_dump(), votes=3, start=2, end=7)
    inner = VotedTag(**tag("ORTHOGRAPHY", "合い", "会い").model_dump(), votes=3, start=5, end=7)
    assert apply_tags(ANSWER, [outer, inner]) == FIXED          # 안쪽은 바깥에 포함 → 바깥만 적용
    clash = VotedTag(**tag("ORTHOGRAPHY", "合い", "逢い").model_dump(), votes=3, start=5, end=7)
    assert apply_tags(ANSWER, [outer, clash]) is None           # 서로 다른 교정 → 충돌


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


def test_top_types_reports_confidence():
    r = record("2026-09-20T10:00:00+09:00", ["PARTICLE", "PARTICLE"])
    r["n_samples"] = 3
    r["errors"][0]["votes"], r["errors"][1]["votes"] = 3, 2
    r["tentative_errors"] = [{"type": "PARTICLE"}]
    t = top_types([r])[0]
    assert (t["unanimous"], round(t["mean_vote_share"], 2), t["tentative"]) == (1, 0.83, 1)


def test_filter_records_strict_by_default():
    current = {"taxonomy_version": "v1", "prompt_version": "p2", "schema_version": "s2", "model": "m"}
    base = {"mode": "grammar", "taxonomy_version": "v1", "schema_version": "s2", "model": "m"}
    now = {**base, "prompt_version": "p2"}
    older = {**base, "prompt_version": "p1"}
    other_taxonomy = {**now, "taxonomy_version": "v0"}
    records = [now, older, other_taxonomy]
    assert filter_records(records, "grammar", current) == [now]
    assert filter_records(records, "grammar", current, include_older=True) == [now, older]  # 유형표가 다르면 여전히 제외


def test_top_types_is_deterministic_on_ties():
    records = [record("2026-09-20T10:00:00+09:00", ["VOICE", "CONNECTIVE"])]
    assert [r["code"] for r in top_types(records)] == ["CONNECTIVE", "VOICE"]


def test_streak():
    recs = [record(f"2026-09-{d}T10:00:00+09:00", []) for d in (17, 18, 19)]
    assert streak_days(recs, today=date(2026, 9, 20)) == 3   # 오늘 아직 안 해도 유지
    assert streak_days(recs, today=date(2026, 9, 21)) == 0
