"""개인 코퍼스(빈출 오답, 오타 거르기, 판정 기록)의 테스트. LLM 없음."""

from coach import store
from coach.corpus import (excluded_keys, frequent_patterns, pattern_key, repeated_after_revision,
                          revision_summary, tag_rows, target_candidates, target_outcome, target_summary)
from coach.lang_ja import same_reading
from coach.stats import tag_key, top_types, weekly_trend


def err(type_, original, corrected, start):
    return {"type": type_, "original": original, "corrected": corrected, "start": start,
            "end": start + len(original), "explanation_ko": "", "severity": "error",
            "kr_interference": False, "votes": 3}


def rec(id_, answer, errors, ts="2026-09-29T10:00:00+09:00"):
    return {"id": id_, "timestamp": ts, "topic": "t", "answer": answer, "mode": "grammar",
            "taxonomy_version": "v1", "n_samples": 3, "errors": errors,
            "tentative_errors": [], "untagged_changes": []}


# ---- 일본어 층 ----

def test_same_reading_detects_ime_conversion():
    assert same_reading("合って", "会って") and same_reading("効く", "聞く")
    assert not same_reading("ほぼ", "ほとんど") and not same_reading("を", "に")


def test_pattern_key_lemmatizes_and_adds_governing_verb():
    answer = "昨日友達を会って帰った。"
    particle = err("PARTICLE", "を", "に", 4)
    assert pattern_key(particle, answer) == ("PARTICLE", "を → に", "会う")   # 조사는 걸리는 동사까지
    verb = err("COLLOCATION", "食べて", "飲んで", 2)
    assert pattern_key(verb, "薬を食べて寝た。") == ("COLLOCATION", "食べる → 飲む", "")   # 활용을 없애서 묶는다


# ---- 빈출 오답과 오타 거르기 ----

def test_frequent_needs_two_different_attempts():
    a = rec("a", "友達を会った。", [err("PARTICLE", "を", "に", 2)])
    b = rec("b", "先生を会います。", [err("PARTICLE", "を", "に", 2)])
    once = rec("c", "駅を着いた。", [err("PARTICLE", "を", "に", 1)])   # 걸리는 동사가 달라 다른 패턴
    patterns = frequent_patterns(tag_rows([a, b, once], {}))
    assert [(p["edit"], p["governing"], p["attempts"]) for p in patterns] == [("を → に", "会う", 2)]


def test_slip_label_and_ime_candidate_are_excluded():
    a = rec("a", "友達に合った。", [err("ORTHOGRAPHY", "合った", "会った", 3)])
    b = rec("b", "先生に合います。", [err("ORTHOGRAPHY", "合います", "会います", 3)])
    rows = tag_rows([a, b], {})
    assert all(r["ime_candidate"] for r in rows)
    assert frequent_patterns(rows) == []                       # 변환 실수 후보는 기본으로 뺀다

    unknown = {tag_key("a", a["errors"][0]): "unknown", tag_key("b", b["errors"][0]): "unknown"}
    assert len(frequent_patterns(tag_rows([a, b], unknown))) == 1   # '몰랐음'으로 판정하면 센다

    slip = {tag_key("a", a["errors"][0]): "slip"}
    rows = tag_rows([a, b], {**unknown, **slip})
    assert frequent_patterns(rows) == []                       # '실수'로 판정하면 반복이 1번으로 줄어 빠진다


def test_only_unknown_filter():
    a = rec("a", "友達を会った。", [err("PARTICLE", "を", "に", 2)])
    b = rec("b", "先生を会います。", [err("PARTICLE", "を", "に", 2)])
    labels = {tag_key("a", a["errors"][0]): "unknown"}
    assert frequent_patterns(tag_rows([a, b], labels)) != []
    assert frequent_patterns(tag_rows([a, b], labels), only_unknown=True) == []   # '몰랐음'은 1번뿐


def test_top_types_respects_exclusions():
    a = rec("a", "友達に合った。", [err("ORTHOGRAPHY", "合った", "会った", 3)])
    rows = tag_rows([a], {})
    assert top_types([a], exclude_keys=excluded_keys(rows)) == []


# ---- 주간 추이 ----

def test_weekly_trend_rates_and_exclusions():
    w1a = rec("a", "友達を会った。", [err("PARTICLE", "を", "に", 2)], ts="2026-09-28T10:00:00+09:00")
    w1b = rec("b", "駅に着いた。", [], ts="2026-09-29T10:00:00+09:00")
    w2 = rec("c", "友達に合った。", [err("ORTHOGRAPHY", "合った", "会った", 3)], ts="2026-10-06T10:00:00+09:00")
    w2["duration_sec"] = 80
    rows = tag_rows([w1a, w1b, w2], {})
    table = weekly_trend([w1a, w1b, w2], ["PARTICLE", "ORTHOGRAPHY"], excluded_keys(rows))
    assert [(t["week"], t["attempts"]) for t in table] == [("2026-W40", 2), ("2026-W41", 1)]
    assert table[0]["rates"] == {"PARTICLE": 0.5, "ORTHOGRAPHY": 0.0}
    assert table[1]["rates"]["ORTHOGRAPHY"] == 0.0     # 변환 실수 후보는 추이에서도 뺀다
    assert table[1]["median_sec"] == 80


# ---- 고쳐 쓰기 (ADR 0013) ----

def test_repeated_after_revision_and_summary():
    parent = rec("a", "友達を会った。", [err("PARTICLE", "を", "に", 2)])
    regrade = [err("PARTICLE", "を", "に", 2)]                  # 고쳐 쓴 답에서도 같은 실수
    repeated = repeated_after_revision(parent, regrade, "友達を会いました。")
    assert repeated == [{"type": "PARTICLE", "edit": "を → に", "governing": "会う"}]

    rows = tag_rows([parent], {})
    revision = {"checks": [{"key": rows[0]["key"], "status": "unchanged"}], "repeated_patterns": repeated}
    summary = revision_summary(rows, [revision])
    assert (summary[0]["edit"], summary[0]["unchanged"], summary[0]["repeated"]) == ("を → に", 1, 1)


# ---- 약점 겨냥 연습 (ADR 0013) ----

TARGET = {"type": "PARTICLE", "edit": "を → に", "governing": "会う"}


def test_target_candidates_include_unknown_once():
    a = rec("a", "友達を会った。", [err("PARTICLE", "を", "に", 2)])
    b = rec("b", "先生を会います。", [err("PARTICLE", "を", "に", 2)])
    once = rec("c", "薬を食べた。", [err("COLLOCATION", "食べた", "飲んだ", 2)])
    labels = {tag_key("c", once["errors"][0]): "unknown"}
    got = [(c["edit"], c["attempts"]) for c in target_candidates(tag_rows([a, b, once], labels))]
    assert got == [("を → に", 2), ("食べる → 飲む", 1)]      # 빈출이 먼저, '몰랐음'은 한 번이어도 후보


def test_target_outcome():
    repeated = rec("a", "先生を会った。", [err("PARTICLE", "を", "に", 2)])
    used = rec("b", "友達に会いました。", [])
    avoided = rec("c", "駅に行った。", [])
    assert [target_outcome(x, TARGET) for x in (repeated, used, avoided)] == ["repeated", "used", "not_used"]
    # に 와 会う 가 따로 떨어져 있으면 '맞게 씀'이 아니다 (화면 확인 중 발견한 오판정)
    scattered = rec("d", "一緒にご飯を食べて、友達と会った。", [])
    assert target_outcome(scattered, TARGET) == "not_used"
    for x in (repeated, used, avoided):
        x["target"] = TARGET
    s = target_summary([repeated, used, avoided])[0]
    assert (s["attempts"], s["repeated"], s["used"], s["not_used"]) == (3, 1, 1, 1)


# ---- 판정 기록 (추가만 하는 파일) ----

def test_labels_last_write_wins_and_can_be_cleared(tmp_path):
    path = tmp_path / "labels.jsonl"
    store.append_label("k1", "slip", path)
    store.append_label("k1", "unknown", path)
    store.append_label("k2", "unsure", path)
    store.append_label("k2", None, path)
    assert store.load_labels(path) == {"k1": "unknown"}
