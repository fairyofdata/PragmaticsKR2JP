"""같은 답을 n번 채점한 결과를 코드로 합친다 (수정 단위 다수결).

같은 유형이고 사용자 답에서 위치가 겹치는 태그를 "같은 지적"으로 묶는다.
n번 중 과반에서 나온 지적만 확정, 나머지는 참고(낮은 확신)로 둔다.
"""

from collections import Counter

from .schemas import VotedTag
from .lang_ja import non_error_diff
from .verify import apply_tags, changed_regions, merged_edits, resolve_span, untagged_changes


def _overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def _merged_tags(confirmed):
    """합쳐진 태그 목록. 단, 합쳐진 수정을 다른 확정 태그가 이미 따로 지적했으면 경고하지 않는다.
    (예: PARTICLE '友達を合って' + ORTHOGRAPHY '合って' 가 함께 확정되면 合→会 는 이미 드러나 있다)"""
    result = []
    for t in confirmed:
        edits = merged_edits(t.original, t.corrected)
        if not edits:
            continue
        others = [o for o in confirmed if o is not t and _overlaps((o.start, o.end), (t.start, t.end))]
        if len(others) + 1 >= len(edits):
            continue
        result.append({"type": t.type, "original": t.original, "corrected": t.corrected,
                       "edits": edits})
    return result


def combine(answer, samples, allowed_codes):
    """samples: GradeResult 리스트. 결과는 Attempt 에 넣을 필드들의 dict."""
    n = len(samples)
    threshold = n // 2 + 1
    dropped = 0
    dropped_width = 0
    ambiguous = 0

    # 1) 태그마다 원문의 위치를 하나로 정한다 (resolve_span).
    #    원문에 없는 인용, 허용되지 않은 유형은 버린다 (검증 D). 전각/반각 차이뿐인 태그도 버린다.
    valid = []  # 샘플별 [(tag, span)]
    for sample in samples:
        changed = [(i1, i2, b) for i1, i2, a, b in changed_regions(answer, sample.minimal_correction)
                   if not non_error_diff(a, b)]
        taken = set()
        kept = []
        for tag in sample.errors:
            span, is_ambiguous = resolve_span(answer, tag, changed, taken)
            if span is None or tag.type not in allowed_codes:
                dropped += 1
            elif non_error_diff(tag.original, tag.corrected):
                dropped_width += 1
            else:
                kept.append((tag, span))
                taken.add(span)
                ambiguous += is_ambiguous
        valid.append(kept)

    # 2) 같은 지적끼리 묶기
    clusters = []  # {"type", "members": [(sample_idx, tag, span)]}
    for idx, kept in enumerate(valid):
        for tag, span in kept:
            for cluster in clusters:
                same_type = cluster["type"] == tag.type
                if same_type and any(_overlaps(span, m[2]) for m in cluster["members"]):
                    cluster["members"].append((idx, tag, span))
                    break
            else:  # for-else: break 없이 끝났을 때(= 맞는 묶음이 없을 때)만 실행
                clusters.append({"type": tag.type, "members": [(idx, tag, span)]})

    # 3) 표 세기
    confirmed, tentative = [], []
    confirmed_ids = set()
    for cluster in clusters:
        votes = len({m[0] for m in cluster["members"]})
        # 대표: 가장 많이 나온 (original, corrected) 쌍. 동률이면 먼저 나온 것.
        pairs = Counter((m[1].original, m[1].corrected) for m in cluster["members"])
        best_pair = pairs.most_common(1)[0][0]
        rep_tag, rep_span = next((m[1], m[2]) for m in cluster["members"]
                                 if (m[1].original, m[1].corrected) == best_pair)
        voted = VotedTag(**rep_tag.model_dump(), votes=votes, start=rep_span[0], end=rep_span[1])
        if votes >= threshold:
            confirmed.append(voted)
            confirmed_ids.update(id(m[1]) for m in cluster["members"])
        else:
            tentative.append(voted)

    # 4) 화면에 보여줄 교정문: 확정된 지적과 가장 잘 맞는 샘플을 고른다
    def score(idx):
        return sum(1 if id(tag) in confirmed_ids else -1 for tag, _ in valid[idx])
    best = max(range(n), key=lambda i: (score(i), -i))
    chosen = samples[best]

    confirmed.sort(key=lambda t: t.start)
    tentative.sort(key=lambda t: t.start)

    # 5) 화면의 교정문은 확정 태그만 원문에 적용해 코드가 만든다 (오류 목록과 항상 일치).
    #    태그끼리 겹쳐 충돌하면 샘플 교정문으로 대신하고 그 사실을 기록한다.
    built = apply_tags(answer, confirmed)
    return {
        "intended_meaning_ko": chosen.intended_meaning_ko,
        "minimal_correction": chosen.minimal_correction,
        "natural_version": chosen.natural_version,
        "confirmed_correction": built if built is not None else chosen.minimal_correction,
        "correction_source": "confirmed_tags" if built is not None else "sample_fallback",
        "errors": confirmed,
        "tentative_errors": tentative,
        # 검증 E: 어느 샘플도 태그하지 않았는데 교정문에서 바뀐 곳
        "untagged_changes": untagged_changes(answer, chosen.minimal_correction,
                                             [(t.start, t.end) for t in confirmed + tentative]),
        "dropped_quotes": dropped,
        "dropped_width": dropped_width,
        "ambiguous_quotes": ambiguous,
        # 검증 E2: 태그 하나에 서로 다른 단어의 수정이 합쳐진 것 (확정 태그만)
        "merged_tags": _merged_tags(confirmed),
        "n_samples": n,
    }
