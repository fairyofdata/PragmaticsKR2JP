"""같은 답을 n번 채점한 결과를 코드로 합친다 (수정 단위 다수결).

같은 유형이고 사용자 답에서 위치가 겹치는 태그를 "같은 지적"으로 묶는다.
n번 중 과반에서 나온 지적만 확정, 나머지는 참고(낮은 확신)로 둔다.
"""

from collections import Counter

from .schemas import VotedTag
from .verify import find_span, untagged_changes


def _overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def combine(answer, samples, allowed_codes):
    """samples: GradeResult 리스트. 결과는 Attempt 에 넣을 필드들의 dict."""
    n = len(samples)
    threshold = n // 2 + 1
    dropped = 0

    # 1) 원문에 없는 인용, 허용되지 않은 유형은 버린다 (검증 D)
    valid = []  # 샘플별 [(tag, span)]
    for sample in samples:
        kept = []
        for tag in sample.errors:
            span = find_span(answer, tag.original)
            if span is None or tag.type not in allowed_codes:
                dropped += 1
            else:
                kept.append((tag, span))
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
    return {
        "intended_meaning_ko": chosen.intended_meaning_ko,
        "minimal_correction": chosen.minimal_correction,
        "natural_version": chosen.natural_version,
        "errors": confirmed,
        "tentative_errors": tentative,
        # 검증 E: 어느 샘플도 태그하지 않았는데 교정문에서 바뀐 곳
        "untagged_changes": untagged_changes(answer, chosen.minimal_correction,
                                             confirmed + tentative),
        "dropped_quotes": dropped,
        "n_samples": n,
    }
