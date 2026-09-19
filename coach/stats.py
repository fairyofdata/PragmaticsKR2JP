"""집계. LLM을 부르지 않는 순수 함수만 둔다. 같은 입력이면 항상 같은 출력."""

from collections import defaultdict
from datetime import date, timedelta

from .taxonomy import OUT_OF_MODE, TAXONOMY_VERSION, name_ko


def filter_records(records, mode, taxonomy_version=TAXONOMY_VERSION):
    """같은 모드·같은 유형표 버전의 기록만. 버전이 다르면 태그의 뜻이 달라서 섞지 않는다."""
    return [r for r in records
            if r["mode"] == mode and r["taxonomy_version"] == taxonomy_version]


def top_types(records, n=5, examples_per_type=3):
    """자주 틀리는 유형 상위 n개.

    순위 기준: 그 유형이 나온 '시도 수' (긴 답 하나에 같은 오류가 몰려 있어도 1로 센다).
    동률이면 전체 건수, 그래도 같으면 코드 알파벳 순 — 항상 같은 순서가 나오게.
    """
    attempts_with = defaultdict(int)
    counts = defaultdict(int)
    interference = defaultdict(int)
    examples = defaultdict(list)

    # 최신 기록이 예시로 먼저 나오도록 역순으로 본다
    for r in sorted(records, key=lambda r: r["timestamp"], reverse=True):
        seen = set()
        for e in r["errors"]:
            code = e["type"]
            if code == OUT_OF_MODE:
                continue
            counts[code] += 1
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

    total = len(records)
    ranked = sorted(attempts_with, key=lambda c: (-attempts_with[c], -counts[c], c))
    return [{
        "code": code,
        "name_ko": name_ko(code),
        "attempts_with": attempts_with[code],
        "share": attempts_with[code] / total if total else 0.0,
        "count": counts[code],
        "kr_interference": interference[code],
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
