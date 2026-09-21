"""'끌려가지 않기' 검증. LLM 없이 코드만으로 확인한다.

D. 인용 검증: 태그의 original 이 사용자 답에 글자 그대로 있는가
E. 누락 검증: 원문 → minimal_correction 에서 바뀐 곳이 모두 태그로 덮였는가
E2. 합침 검출: 태그 하나에 서로 다른 단어의 수정이 여러 개 들어 있는가 (한 오류가 다른 오류에 묻히는 것 방지)

이 파일은 언어를 모른다. 단어를 나누는 일과 "이 차이는 오류가 아니다"라는 판단은 `lang_ja.py` 가 한다.
"""

import difflib
import html

from .lang_ja import non_error_diff, tokenize_chunks


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


def resolve_span(answer, tag, changed, taken):
    """태그가 원문의 어디를 가리키는지 하나로 정한다. 결과: (span, 모호했나). 원문에 없으면 (None, False).

    같은 문자열(특히 조사 「を」)이 답에 여러 번 나오면 첫 위치만 쓰면 안 된다.
    후보를 아래 순서로 줄여 나간다. 어느 단계에서 후보가 0개가 되면 그 단계는 건너뛴다.
      1. 문맥: 태그가 준 앞뒤 글자(context_before/after)와 맞는 위치
      2. 같은 샘플의 다른 태그가 이미 가져간 위치는 뺀다
      3. 그 샘플의 교정문에서 실제로 바뀐 곳과 겹치는 위치
      4. 그중에서도 바뀐 내용이 태그의 corrected 와 같은 위치
    그래도 여럿이면 첫 번째를 쓰고 '모호'로 표시한다.

    changed: [(시작, 끝, 교정 조각)] — 원문과 그 샘플 교정문의 차이
    taken: 같은 샘플에서 이미 쓰인 위치 집합
    """
    candidates = all_spans(answer, tag.original)
    if not candidates:
        return None, False

    def touches(span, i1, i2):
        s, e = span
        return (s <= i1 <= e) if i1 == i2 else (s < i2 and i1 < e)

    steps = [
        lambda sp: (answer[:sp[0]].endswith(tag.context_before)
                    and answer[sp[1]:].startswith(tag.context_after)),
        lambda sp: sp not in taken,
        lambda sp: any(touches(sp, i1, i2) for i1, i2, _ in changed),
        lambda sp: any(touches(sp, i1, i2) and b == tag.corrected for i1, i2, b in changed),
    ]
    for keep in steps:
        narrowed = [sp for sp in candidates if keep(sp)]
        if narrowed:
            candidates = narrowed
    return candidates[0], len(candidates) > 1


def apply_tags(answer, tags):
    """확정 태그의 original→corrected 를 원문에 적용한 교정문. 태그끼리 충돌하면 None.

    한 태그가 다른 태그를 완전히 감싸고, 감싼 쪽의 교정에 안쪽 교정이 이미 들어 있으면
    (PARTICLE 友達を合って→友達に会って 안의 ORTHOGRAPHY 合って→会って) 바깥 것만 적용한다.
    """
    chosen = []
    for t in sorted(tags, key=lambda t: (t.start, -(t.end - t.start))):
        if chosen and t.start < chosen[-1].end:
            outer = chosen[-1]
            if t.end <= outer.end and t.corrected in outer.corrected:
                continue
            return None
        chosen.append(t)
    out, pos = [], 0
    for t in chosen:
        out.append(answer[pos:t.start])
        out.append(t.corrected)
        pos = t.end
    out.append(answer[pos:])
    return "".join(out)


def changed_regions(answer, corrected):
    """글자 단위 diff. 바뀐 곳마다 (원문 시작, 원문 끝, 원문 조각, 교정 조각)."""
    matcher = difflib.SequenceMatcher(a=answer, b=corrected, autojunk=False)
    regions = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            regions.append((i1, i2, answer[i1:i2], corrected[j1:j2]))
    return regions


def word_edits(original, corrected):
    """두 문자열의 차이를 '바뀐 단어' 단위로 센다."""
    a, b = tokenize_chunks(original), tokenize_chunks(corrected)
    pairs = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        a_part, b_part = a[i1:i2], b[j1:j2]
        if len(a_part) == len(b_part):
            pairs.extend((x, y) for x, y in zip(a_part, b_part) if x != y)
        else:
            # 개수가 달라 짝지을 수 없으면 한 덩어리로 본다 (連絡しました → ご連絡いたしました)
            pairs.append(("".join(a_part), "".join(b_part)))
    return [{"original": x, "corrected": y} for x, y in pairs if not non_error_diff(x, y)]


def merged_edits(original, corrected):
    """태그 하나에 서로 다른 단어의 수정이 합쳐져 있으면 그 목록, 아니면 빈 목록.

    양쪽이 모두 비어 있지 않은 수정이 2개 이상일 때만 경고한다.
    (경어로 글자를 끼워 넣기만 한 수정 連絡→ご連絡 은 한 단어 안의 일이라 경고하지 않는다)
    """
    edits = [e for e in word_edits(original, corrected) if e["original"] and e["corrected"]]
    return edits if len(edits) >= 2 else []


def untagged_changes(answer, corrected, spans):
    """태그 없이 조용히 고친 곳 목록. spans: 태그들이 가리키는 위치 [(시작, 끝)] (resolve_span 으로 정한 것).

    바뀐 글자 하나하나가 어떤 태그 범위 안에 있어야 '덮였다'고 본다.
    (인접한 두 수정 を→に, 合→会 가 diff 에서 한 덩어리로 합쳐져도,
     を 태그 하나로 合 까지 덮인 것으로 치지 않기 위해.
     또 「を」 태그 하나가 답 안의 모든 「を」를 덮는 것으로 치지 않기 위해 위치는 하나로 정해서 받는다)
    """
    covered = set()
    for s, e in spans:
        covered.update(range(s, e))

    result = []
    for i1, i2, a_part, b_part in changed_regions(answer, corrected):
        if non_error_diff(a_part, b_part):
            continue
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
