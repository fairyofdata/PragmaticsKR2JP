"""'끌려가지 않기' 검증. LLM 없이 코드만으로 확인한다.

D. 인용 검증: 태그의 original 이 사용자 답에 글자 그대로 있는가
E. 누락 검증: 원문 → minimal_correction 에서 바뀐 곳이 모두 태그로 덮였는가
E2. 합침 검출: 태그 하나에 서로 다른 수정이 여러 개 들어 있는가 (한 오류가 다른 오류에 묻히는 것 방지)
"""

import difflib
import html
import unicodedata


def width_only(a, b):
    """두 문자열이 전각/반각 같은 '모양'만 다른가. (NFKC = 모양만 다른 글자를 하나로 맞추는 유니코드 표준 변환)
    원문 저장에는 쓰지 않고, 비교할 때만 쓴다."""
    return a != b and unicodedata.normalize("NFKC", a) == unicodedata.normalize("NFKC", b)


def _script(ch):
    if "぀" <= ch <= "ゟ":
        return "hiragana"
    if "゠" <= ch <= "ヿ":
        return "katakana"
    if "一" <= ch <= "鿿" or ch == "々":
        return "kanji"
    return "other"


def _pieces(text):
    """히라가나 뒤에 한자·가타카나가 오면 새 단어가 시작된 것으로 보고 자른다.
    'を合' → ['を', '合'] (조사 + 다음 단어) / '食べ' → ['食べ'] (한자 + 오쿠리가나는 한 단어)"""
    pieces = []
    for ch in text:
        new_word = (pieces and _script(pieces[-1][-1]) == "hiragana"
                    and _script(ch) in ("kanji", "katakana"))
        if not pieces or new_word:
            pieces.append(ch)
        else:
            pieces[-1] += ch
    return pieces


def split_edits(original, corrected):
    """태그 하나 안에 들어 있는 수정들을 나눈다.

    한 덩어리로 바뀐 곳이라도 양쪽이 같은 모양의 조각으로 나뉘면
    (예: 'を合'→'に会' = 조사+한자 / 조사+한자) 서로 다른 단어를 고친 것으로 본다.
    """
    edits = []
    for _, _, a_part, b_part in changed_regions(original, corrected):
        a_pcs, b_pcs = _pieces(a_part), _pieces(b_part)
        same_shape = (len(a_pcs) == len(b_pcs) > 1
                      and [_script(p[0]) for p in a_pcs] == [_script(p[0]) for p in b_pcs])
        if same_shape:
            edits.extend((a, b) for a, b in zip(a_pcs, b_pcs) if a != b)
        else:
            edits.append((a_part, b_part))
    return [{"original": a, "corrected": b} for a, b in edits if not width_only(a, b)]


def _has_kanji(text):
    return any(_script(ch) == "kanji" for ch in text)


def merged_edits(original, corrected):
    """태그 하나에 서로 다른 단어의 수정이 합쳐져 있으면 그 수정 목록, 아니면 빈 목록.

    경고 조건(오탐을 줄이려고 좁게 잡음): 양쪽이 모두 비어 있지 않은 수정이 2개 이상이고,
    그중 하나는 한자를 한자로 바꾼 것. 경어처럼 글자를 끼워 넣기만 한 수정(連絡→ご連絡)은 제외된다.
    """
    edits = [e for e in split_edits(original, corrected) if e["original"] and e["corrected"]]
    if len(edits) >= 2 and any(_has_kanji(e["original"]) and _has_kanji(e["corrected"]) for e in edits):
        return edits
    return []


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
        if width_only(a_part, b_part):
            continue  # 전각/반각 차이는 오류가 아니다
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
