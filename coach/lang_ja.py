"""일본어에 대한 지식은 이 파일에만 둔다.

`coach/verify.py` 는 언어를 모른다. 필요한 것을 여기서 두 개만 받아 쓴다.
  tokenize_chunks(text) -> 단어 덩어리 목록 (문절에 가까운 단위)
  non_error_diff(a, b)  -> 이 차이는 오류로 보지 않아도 되는가

다른 언어로 확장할 때는 같은 두 함수를 가진 파일을 하나 더 만들면 된다.
"""

import unicodedata

# SudachiPy(형태소 분석기)가 있으면 쓰고, 없으면 표기 기반 근사로 돌아간다.
try:
    from sudachipy import Dictionary, SplitMode

    _tokenizer = Dictionary().create()
    TOKENIZER = "sudachi"
except Exception:                                    # 미설치, 사전 없음 등
    _tokenizer = None
    TOKENIZER = "script-heuristic"

# 앞 덩어리에 붙는 품사 (조사·조동사·접미사 등은 앞말과 한 덩어리로 본다)
_ATTACH_POS = {"助詞", "助動詞", "接尾辞", "補助記号", "空白"}
# 「連絡する」「〜てあげる」처럼 앞말에 붙어 쓰이는 동사·형용사
_ATTACH_SUB = "非自立可能"


def _chunks_sudachi(text):
    chunks = []
    prev_pos, prev_surface = None, ""
    for m in _tokenizer.tokenize(text, SplitMode.C):
        pos = m.part_of_speech()
        # 「連絡+する」처럼 명사에 붙거나, 「〜て+あげる」처럼 て/で 뒤에 오는 경우에만 앞말에 붙인다.
        # (「合う」처럼 복합동사로도 쓰여 非自立可能 으로 분류되는 말을 조사 뒤에서 붙이지 않기 위해)
        helper = pos[1] == _ATTACH_SUB and (prev_pos == "名詞" or prev_surface in ("て", "で"))
        attach = pos[0] in _ATTACH_POS or helper or prev_pos == "接頭辞"   # ご + 連絡
        if chunks and attach:
            chunks[-1] += m.surface()
        else:
            chunks.append(m.surface())
        prev_pos, prev_surface = pos[0], m.surface()
    return chunks


def _script(ch):
    if "぀" <= ch <= "ゟ":
        return "hiragana"
    if "゠" <= ch <= "ヿ":
        return "katakana"
    if "一" <= ch <= "鿿" or ch == "々":
        return "kanji"
    return "other"


def _chunks_fallback(text):
    """형태소 분석기가 없을 때. 히라가나 뒤에 한자·가타카나가 오면 새 단어로 본다.
    'を合' → ['を', '合'] (조사 다음에 새 단어) / '食べ' → ['食べ'] (오쿠리가나는 한 단어)"""
    chunks = []
    for ch in text:
        new_word = (chunks and _script(chunks[-1][-1]) == "hiragana"
                    and _script(ch) in ("kanji", "katakana"))
        if not chunks or new_word:
            chunks.append(ch)
        else:
            chunks[-1] += ch
    return chunks


def tokenize_chunks(text):
    return _chunks_sudachi(text) if _tokenizer else _chunks_fallback(text)


def _fold(text):
    """폭만 다른 글자를 맞춘다. 단, 반각 가타카나(ｻｰﾊﾞｰ)나 ㈱ 같은 글자는 건드리지 않는다.
    (NFKC 를 그대로 쓰면 ｻｰﾊﾞｰ→サーバー 같은 진짜 표기 오류까지 '차이 없음'이 되어 버린다)"""
    out = []
    for ch in text:
        folded = unicodedata.normalize("NFKC", ch)
        # 한 글자짜리 ASCII(문장부호, 공백, 숫자, 영문)로 바뀌는 경우만 폭 차이로 본다
        out.append(folded if len(folded) == 1 and folded.isascii() else ch)
    return "".join(out)


def non_error_diff(a, b):
    """문장부호·공백·숫자·영문의 전각/반각 차이뿐이면 오류로 보지 않는다."""
    return a != b and _fold(a) == _fold(b)
