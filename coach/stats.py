"""집계. LLM을 부르지 않는 순수 함수만 둔다. 같은 입력이면 항상 같은 출력."""

from collections import defaultdict
from datetime import date, timedelta

from .taxonomy import OUT_OF_MODE, name_ko


VERSION_KEYS = ("taxonomy_version", "prompt_version", "schema_version", "model")


def filter_records(records, mode, current, include_older=False):
    """집계에 넣을 기록을 고른다.

    기본(엄격): 유형표·프롬프트·스키마·모델이 모두 현재(current)와 같은 기록만. 측정 도구가 바뀌면 분포도 바뀌므로 섞지 않는다.
    include_older=True: 유형표만 같으면 포함한다 (태그의 뜻은 같다). 이때는 화면에 섞인 버전 구성을 함께 보여준다.
    유형표가 다르면 태그의 뜻이 달라서 어느 경우에도 섞지 않는다.
    """
    same = [r for r in records
            if r["mode"] == mode and r["taxonomy_version"] == current["taxonomy_version"]]
    if include_older:
        return same
    return [r for r in same if all(r.get(k) == current[k] for k in VERSION_KEYS)]


def version_mix(records):
    """기록들이 어떤 (프롬프트, 스키마, 모델) 조합으로 만들어졌는지 건수. 많은 순."""
    mix = defaultdict(int)
    for r in records:
        mix[(r.get("prompt_version"), r.get("schema_version"), r.get("model"))] += 1
    return sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))


def top_types(records, n=5, examples_per_type=3):
    """자주 틀리는 유형 상위 n개.

    순위 기준: 그 유형이 나온 '시도 수' (긴 답 하나에 같은 오류가 몰려 있어도 1로 센다).
    동률이면 전체 건수, 그래도 같으면 코드 알파벳 순 — 항상 같은 순서가 나오게.
    """
    attempts_with = defaultdict(int)
    counts = defaultdict(int)
    interference = defaultdict(int)
    examples = defaultdict(list)
    votes = defaultdict(list)       # 확정 태그의 표 수 (신뢰도 표시용)
    tentative = defaultdict(int)    # 과반 미달로 순위에서 뺀 건수 (신뢰도 표시용)

    # 최신 기록이 예시로 먼저 나오도록 역순으로 본다
    for r in sorted(records, key=lambda r: r["timestamp"], reverse=True):
        seen = set()
        for e in r["errors"]:
            code = e["type"]
            if code == OUT_OF_MODE:
                continue
            counts[code] += 1
            votes[code].append((e.get("votes", 1), r.get("n_samples", 1)))
            if e["kr_interference"]:
                interference[code] += 1
            seen.add(code)
            if len(examples[code]) < examples_per_type:
                examples[code].append({
                    "answer": r["answer"],
                    "original": e["original"],
                    "corrected": e["corrected"],
                    "explanation_ko": e["explanation_ko"],
                    "severity": e["severity"],
                    "topic": r["topic"],
                })
        for code in seen:
            attempts_with[code] += 1
        for e in r.get("tentative_errors", []):
            tentative[e["type"]] += 1

    total = len(records)
    ranked = sorted(attempts_with, key=lambda c: (-attempts_with[c], -counts[c], c))
    return [{
        "code": code,
        "name_ko": name_ko(code),
        "attempts_with": attempts_with[code],
        "share": attempts_with[code] / total if total else 0.0,
        "count": counts[code],
        "kr_interference": interference[code],
        # 신뢰도: 확정 태그가 n번 채점 중 평균 몇 번 나왔나, 몇 건이 전원 일치였나, 낮은 확신으로 빠진 건수
        "unanimous": sum(1 for v, n in votes[code] if v >= n),
        "mean_vote_share": (sum(v / n for v, n in votes[code]) / len(votes[code])) if votes[code] else 0.0,
        "tentative": tentative[code],
        "examples": examples[code],
    } for code in ranked[:n]]


def summary_counts(records):
    """요약 화면 상단 숫자들."""
    return {
        "attempts": len(records),
        "errors": sum(len(r["errors"]) for r in records),
        "out_of_mode": sum(1 for r in records for e in r["errors"] if e["type"] == OUT_OF_MODE),
        "tentative": sum(len(r["tentative_errors"]) for r in records),
        "untagged_changes": sum(len(r["untagged_changes"]) for r in records),
        "error_free": sum(1 for r in records if not r["errors"]),
    }


def streak_days(records, today=None):
    """오늘(또는 어제)까지 하루도 빠지지 않고 연습한 날 수. 오늘 아직 안 했어도 어제까지 이어졌으면 유지."""
    today = today or date.today()
    days = {date.fromisoformat(r["timestamp"][:10]) for r in records}
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak
