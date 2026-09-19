"""'끌려가지 않기' 검증. LLM 없이 코드만으로 확인한다.

D. 인용 검증: 태그의 original 이 사용자 답에 글자 그대로 있는가
E. 누락 검증: 원문 → minimal_correction 에서 바뀐 곳이 모두 태그로 덮였는가
"""

import difflib
import html


def find_span(answer, original):
    """original 이 answer 안에서 처음 나오는 위치 (start, end). 없으면 None."""
    if not original:
        return None
    start = answer.find(original)
    if start < 0:
        return None
    return (start, start + len(original))


def all_spans(answer, original):
    """original 이 나오는 모든 위치. 같은 글자가 여러 번 나올 수 있으므로."""
    spans = []
    if not original:
        return spans
    start = answer.find(original)
    while start >= 0:
        spans.append((start, start + len(original)))
        start = answer.find(original, start + 1)
    return spans


def changed_regions(answer, corrected):
    """글자 단위 diff. 바뀐 곳마다 (원문 시작, 원문 끝, 원문 조각, 교정 조각)."""
    matcher = difflib.SequenceMatcher(a=answer, b=corrected, autojunk=False)
    regions = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            regions.append((i1, i2, answer[i1:i2], corrected[j1:j2]))
    return regions


def untagged_changes(answer, corrected, tags):
    """태그 없이 조용히 고친 곳 목록.

    바뀐 글자 하나하나가 어떤 태그 범위 안에 있어야 '덮였다'고 본다.
    (인접한 두 수정 を→に, 合→会 가 diff 에서 한 덩어리로 합쳐져도,
     を 태그 하나로 合 까지 덮인 것으로 치지 않기 위해)
    """
    spans = []
    for tag in tags:
        spans.extend(all_spans(answer, tag.original))
    covered = set()
    for s, e in spans:
        covered.update(range(s, e))

    result = []
    for i1, i2, a_part, b_part in changed_regions(answer, corrected):
        if i1 == i2:
            # 삽입: 길이 0인 지점. 태그 범위 안이나 경계면 덮인 것으로 본다.
            if not any(s <= i1 <= e for s, e in spans):
                result.append({"original": a_part, "corrected": b_part})
            continue
        uncovered = [i for i in range(i1, i2) if i not in covered]
        if not uncovered:
            continue
        if len(a_part) == len(b_part):
            # 글자 수가 같은 치환이면 덮이지 않은 글자만, 연속된 것끼리 묶어서 보여준다
            runs = [[uncovered[0]]]
            for i in uncovered[1:]:
                if i == runs[-1][-1] + 1:
                    runs[-1].append(i)
                else:
                    runs.append([i])
            for run in runs:
                s, e = run[0], run[-1] + 1
                result.append({"original": answer[s:e], "corrected": b_part[s - i1:e - i1]})
        else:
            result.append({"original": a_part, "corrected": b_part})
    return result


def diff_html(answer, corrected):
    """화면용: 지운 글자는 빨간 취소선, 넣은 글자는 초록 밑줄."""
    matcher = difflib.SequenceMatcher(a=answer, b=corrected, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out.append(html.escape(answer[i1:i2]))
            continue
        if i2 > i1:
            out.append('<del style="color:#c62828">' + html.escape(answer[i1:i2]) + "</del>")
        if j2 > j1:
            out.append('<ins style="color:#2e7d32">' + html.escape(corrected[j1:j2]) + "</ins>")
    return "".join(out)
