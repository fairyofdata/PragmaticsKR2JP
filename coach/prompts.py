"""프롬프트. 내용을 바꾸면 PROMPT_VERSION 을 올린다 (기록끼리 비교할 수 있게).

few-shot 방침: 답 전체를 보여주는 예시는 넣지 않는다 (주제·유형 쏠림 방지).
유형마다 과제와 무관한 짧은 대비쌍 1개씩만, 모든 유형에 똑같이 둔다.
"""

from .taxonomy import ERROR_TYPES, MODES, OUT_OF_MODE, codes_for_mode

PROMPT_VERSION = "p0"

# 주제별로 코드가 고르는 장면 (매체, 관계). LLM이 아니라 코드가 정하므로 분포를 통제할 수 있다.
TOPICS = {
    "업무 메일": [("메일", "사외 거래처"), ("메일", "사내 상사")],
    "회의 발언": [("구두", "사내 회의 참석자")],
    "사내 채팅": [("채팅", "사내 동료"), ("채팅", "사내 상사")],
    "일상": [("구두", "친한 친구"), ("채팅", "친한 친구")],
    "자기소개": [("구두", "처음 만나는 사내 사람들")],
}


def task_prompt(topic, medium, relationship):
    return f"""당신은 일본에서 일하는 한국인 엔지니어를 위한 일본어 작문 과제를 냅니다.

주제: {topic}
매체: {medium}
상대와의 관계: {relationship}

조건:
- situation_ko: 한국어로 상황을 2~3문장으로 설명한다. 구체적인 장면(누가, 왜, 무엇을)을 넣는다.
- instruction_ko: 사용자가 일본어로 무엇을 써야 하는지 한국어로 1~2문장. 분량은 일본어 1~4문장 정도.
- 일본어 모범답안이나 일본어 표현 힌트는 절대 쓰지 않는다. 한국어로만 쓴다.
"""


def _codebook(mode):
    lines = []
    for code in codes_for_mode(mode):
        if code == OUT_OF_MODE:
            continue
        t = ERROR_TYPES[code]
        line = f"- {code} ({t['name_ko']}): {t['definition']}"
        if t["boundary"]:
            line += f" 경계: {t['boundary']}"
        if t["contrast"]:
            line += f" 대비: {t['contrast']}"
        lines.append(line)
    return "\n".join(lines)


def grade_prompt(mode, task, medium, relationship, answer):
    other_mode = "expression" if mode == "grammar" else "grammar"
    return f"""당신은 한국어 모어 화자의 일본어 작문을 검사하는 주석자(annotator)입니다.
점수를 매기지 말고, 아래 유형표에 따라 오류의 위치와 유형만 표시하세요.

# 가장 중요한 규칙: 끌려가지 말 것
- 사용자의 답을 글자 그대로 읽으세요. "아마 이런 뜻이겠지"라고 좋게 해석해서 오류를 넘기지 마세요.
- 일본인이 뜻을 알아들을 수 있더라도, 원어민이 그렇게 쓰지 않는다면 표시하세요.
- 오타와 IME 변환 실수(同音異字)도 표시하세요. 의도한 단어로 조용히 바꾸지 마세요.
- 반대로, 맞는 부분을 취향대로 바꾸지 마세요. 오류가 없으면 errors 는 빈 목록이 정답입니다.

# 순서
1. intended_meaning_ko: 사용자가 전하려 한 뜻을 한국어로 적는다.
2. minimal_correction: 오류만 고친 일본어. 사용자의 단어 선택과 문장 구조는 최대한 유지한다.
3. natural_version: 이 장면(매체: {medium}, 상대: {relationship})에서 원어민이 쓸 자연스러운 일본어.
4. errors: minimal_correction 에서 바꾼 곳마다 태그 하나씩. 바꾼 곳은 모두 태그가 있어야 한다.

# 태그 규칙
- original: 사용자 답에 **글자 그대로** 있는 부분을 복사한다. 고친 형태로 인용하지 않는다.
  빠진 말(조사 누락 등)은 바로 앞뒤 단어를 포함해서 인용한다.
- 오류 한 곳에 태그 하나. 두 유형에 걸치면 유형표에서 위쪽 유형을 고른다.
- severity: error = 문법적으로 틀림 / unnatural = 문법은 맞지만 원어민이 쓰지 않는 표현.
- kr_interference: 한국어를 그대로 옮긴 것이 원인으로 보이면 true.
- explanation_ko: 한국어로 1~2문장. 왜 틀렸는지와 올바른 쓰임.

# 모드: {MODES[mode]}
이 모드의 유형(위쪽이 우선):
{_codebook(mode)}

이 모드 밖의 오류({MODES[other_mode]} 쪽)도 minimal_correction 에서 고치고,
세부 유형 없이 {OUT_OF_MODE} 로 태그하세요.

# 과제
상황: {task.situation_ko}
지시: {task.instruction_ko}

# 사용자의 답 (이 문자열 그대로 검사)
<<<
{answer}
>>>
"""


def plain_grade_prompt(mode, task, medium, relationship, answer):
    """실험 비교용 (a) 조건: 유형 이름만 주고 지침·규칙은 없는 단순 지시."""
    codes = ", ".join(codes_for_mode(mode))
    return f"""다음 일본어 작문의 오류를 고치고 태그를 붙이세요.
사용 가능한 유형: {codes}
original 에는 원문의 해당 부분, corrected 에는 고친 부분, explanation_ko 에는 한국어 해설을 넣으세요.
minimal_correction 에는 고친 문장, natural_version 에는 자연스러운 문장, intended_meaning_ko 에는 뜻을 넣으세요.

상황: {task.situation_ko}
지시: {task.instruction_ko}
답:
{answer}
"""
