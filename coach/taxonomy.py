"""오류 유형표 v0.

규칙
- 코드(영문)는 저장용. 한 번 쓴 코드는 바꾸지 않는다. 이름·설명은 바뀌어도 된다.
- 유형을 추가·삭제·병합하면 TAXONOMY_VERSION 을 올린다.
- mode: "grammar"(문법 모드), "expression"(표현 모드), "common"(두 모드 공통)
"""

TAXONOMY_VERSION = "v0"

MODES = {
    "grammar": "문법 모드 — 형태·통사 (정확성)",
    "expression": "표현 모드 — 어휘·화용 (적절성)",
}

# 선택한 모드 밖의 오류. 세부 유형 없이 이 태그 하나만 붙인다 (집계에서는 제외).
OUT_OF_MODE = "OUT_OF_MODE"

# 표 안의 순서가 곧 우선순위다: 두 유형에 걸치면 위쪽 유형을 고른다.
ERROR_TYPES = {
    # ---- 공통 ----
    "ORTHOGRAPHY": {
        "name_ko": "표기·오타·변환 실수",
        "mode": "common",
        "definition": "가나·한자·오쿠리가나·장음·문장부호의 잘못, 오타, IME 변환 실수(同音異字).",
        "boundary": "읽기가 같은데 한자만 틀렸으면 여기. 읽기까지 다른 다른 단어를 골랐으면 WORD_CHOICE.",
        "contrast": "話を聞く ○ / 話を効く ✕",
    },
    # ---- 문법 모드 ----
    "PARTICLE": {
        "name_ko": "조사",
        "mode": "grammar",
        "definition": "격조사·부조사(は・が・を・に・で・へ・と・も 등)의 선택, 누락, 과잉.",
        "boundary": "동사가 요구하는 격(〜に乗る 등)도 여기.",
        "contrast": "バスに乗る ○ / バスを乗る ✕",
    },
    "CONJUGATION": {
        "name_ko": "활용",
        "mode": "grammar",
        "definition": "동사·형용사·조동사의 형태가 틀림(て형, た형, 가능형, な/い형용사 등).",
        "boundary": "형태가 틀린 것만. 형태는 맞는데 시제 선택이 틀리면 TENSE_ASPECT.",
        "contrast": "書いて ○ / 書きて ✕",
    },
    "TENSE_ASPECT": {
        "name_ko": "시제·상",
        "mode": "grammar",
        "definition": "る / た / ている / ていた / てある 등의 선택.",
        "boundary": "",
        "contrast": "(기혼이라는 뜻) もう結婚しています ○ / もう結婚します ✕",
    },
    "VOICE": {
        "name_ko": "태·수수·자타동사",
        "mode": "grammar",
        "definition": "자동사/타동사, 수동, 사역, あげる・くれる・もらう 및 〜てくれる/〜てもらう의 선택.",
        "boundary": "させていただく 의 경어 측면은 POLITENESS(표현 모드). 여기서는 문법 구조만.",
        "contrast": "(내가 받음) 先生が教えてくれた ○ / 先生が教えてあげた ✕",
    },
    "CONNECTIVE": {
        "name_ko": "접속·문장 연결",
        "mode": "grammar",
        "definition": "て・ので・から・のに・が・けど・たら・ば 등 절과 절의 논리 관계.",
        "boundary": "논리 관계(순접/역접/조건)가 틀린 것. ので/から 의 격식 차이는 REGISTER.",
        "contrast": "頑張ったのに落ちた ○ / 頑張ったので落ちた ✕",
    },
    # ---- 표현 모드 ----
    "POLITENESS": {
        "name_ko": "경어·정중체",
        "mode": "expression",
        "definition": "존경어·겸양어·정중어의 선택과 형태, です・ます체와 보통체의 혼용, ウチ/ソト.",
        "boundary": "경어의 형태와 수준만. 그 밖의 딱딱함·가벼움은 REGISTER.",
        "contrast": "お客様がいらっしゃいました ○ / お客様が参りました ✕",
    },
    "REGISTER": {
        "name_ko": "문체·장면 적합성",
        "mode": "expression",
        "definition": "書き言葉/話し言葉, 격식의 정도, 매체(메일·채팅·구두)와 관계에 맞는 관용 표현.",
        "boundary": "문법적으로 맞고 경어 형태도 맞지만 이 장면에 어울리지 않는 것.",
        "contrast": "(거래처 메일) 少々お待ちください ○ / ちょっと待ってください ✕",
    },
    "SENTENCE_END": {
        "name_ko": "문말 표현",
        "mode": "expression",
        "definition": "と思います・んです・かもしれません・ようです・でしょうか 등 모달리티.",
        "boundary": "경어 수준이 아니라 단정·추측·완곡의 정도가 문제일 때.",
        "contrast": "(의견을 말할 때) 〜だと思います ○ / 〜です ✕ (지나친 단정)",
    },
    "WORD_CHOICE": {
        "name_ko": "어휘 선택",
        "mode": "expression",
        "definition": "뜻은 통하지만 맥락·뉘앙스에 맞지 않는 단어. 유의어, 조수사, 의성어·의태어 포함.",
        "boundary": "단어 하나의 선택. 단어 조합이 관습에 어긋나면 COLLOCATION.",
        "contrast": "(결근) 体調不良で休みます ○ / 体調不良で休憩します ✕",
    },
    "COLLOCATION": {
        "name_ko": "연어·관용 표현",
        "mode": "expression",
        "definition": "관습적으로 함께 쓰이는 단어 조합, 관용구.",
        "boundary": "",
        "contrast": "風邪をひく ○ / 風邪にかかる ✕",
    },
    "DISCOURSE": {
        "name_ko": "문장 구조·담화",
        "mode": "expression",
        "definition": "어순, 주어·목적어의 과잉 명시, 지시어(こそあ), 정보 배열, 지나치게 긴 문장.",
        "boundary": "문장 하나 안의 문법이 아니라 문장 간 흐름이나 구성이 문제일 때.",
        "contrast": "昨日映画を見ました。面白かったです。 ○ / 私は昨日映画を見ました。私はその映画が面白かったです。 ✕",
    },
    # ---- 공통 (맨 마지막) ----
    "OTHER": {
        "name_ko": "기타",
        "mode": "common",
        "definition": "위 어느 유형에도 맞지 않는 오류.",
        "boundary": "이 비율이 커지면 유형표를 고칠 신호다.",
        "contrast": "",
    },
}


def codes_for_mode(mode):
    """이 모드에서 붙일 수 있는 태그 코드 목록 (우선순위 순서, OUT_OF_MODE 포함)."""
    codes = [c for c, t in ERROR_TYPES.items() if t["mode"] in (mode, "common")]
    return codes + [OUT_OF_MODE]


def name_ko(code):
    if code == OUT_OF_MODE:
        return "모드 밖 오류"
    return ERROR_TYPES[code]["name_ko"]
