"""LLM 호출은 이 파일에만 둔다. 제공자를 바꿀 때는 이 파일만 고친다.

설정은 환경변수(.env)로:
  LLM_PROVIDER     openai 또는 gemini (기본 openai)
  OPENAI_API_KEY / GEMINI_API_KEY   (쓰는 쪽 하나만 있으면 됨)
  GRADER_MODEL     채점 모델   (기본 openai: gpt-5.6-terra / gemini: gemini-3.8-flash)
  TASK_MODEL       출제 모델   (기본 openai: gpt-5.6-luna  / gemini: gemini-3.1-flash-lite)
  GRADER_REASONING 채점 모델의 추론 수준 (기본 low)
  N_SAMPLES        같은 답을 몇 번 채점해 다수결할지 (기본 3)

temperature 는 건드리지 않는다. OpenAI 추론 모델은 지원하지 않고, Gemini 3 는 기본값 1.0 유지를
공식 권장한다. 흔들림은 다수결로 다룬다.
"""

import copy
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from dotenv import load_dotenv
from pydantic import ValidationError

from .prompts import PROMPT_VERSION, grade_prompt, task_prompt
from .schemas import SCHEMA_VERSION, Attempt, GradeResult, Task
from .taxonomy import TAXONOMY_VERSION, codes_for_mode
from .voting import combine

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "openai")
_DEFAULTS = {
    #          채점 모델            출제 모델                출제 추론 수준
    "openai": ("gpt-5.6-terra", "gpt-5.6-luna", "none"),
    "gemini": ("gemini-3.8-flash", "gemini-3.1-flash-lite", "low"),
}
GRADER_MODEL = os.getenv("GRADER_MODEL", _DEFAULTS[PROVIDER][0])
TASK_MODEL = os.getenv("TASK_MODEL", _DEFAULTS[PROVIDER][1])
TASK_REASONING = _DEFAULTS[PROVIDER][2]
GRADER_REASONING = os.getenv("GRADER_REASONING", "low")
N_SAMPLES = int(os.getenv("N_SAMPLES", "3"))

_client = None
_client_lock = threading.Lock()


def client():
    # 여러 스레드가 동시에 불러도 클라이언트는 하나만 만든다 (lock = 한 번에 한 스레드만 들어가게 하는 자물쇠).
    # 둘이 만들어지면 덮어써진 쪽이 정리되면서 "client has been closed" 오류가 날 수 있다.
    global _client
    with _client_lock:
        if _client is None:
            if PROVIDER == "openai":
                from openai import OpenAI
                _client = OpenAI()        # OPENAI_API_KEY 를 환경변수에서 읽는다
            else:
                from google import genai
                _client = genai.Client()  # GEMINI_API_KEY 를 환경변수에서 읽는다
    return _client


def _grade_schema(mode):
    """GradeResult 의 JSON 스키마에 '이 모드에서 쓸 수 있는 유형 코드'를 enum 으로 넣는다."""
    schema = GradeResult.model_json_schema()
    schema["$defs"]["ErrorTag"]["properties"]["type"]["enum"] = codes_for_mode(mode)
    return schema


def _strict(schema):
    """OpenAI strict 모드 규칙에 맞춘 사본: 모든 객체에 additionalProperties=false, 모든 필드 required."""
    schema = copy.deepcopy(schema)

    def fix(node):
        if isinstance(node, dict):
            node.pop("default", None)  # strict 모드는 기본값 표기를 받지 않는다 (모든 필드를 필수로 받음)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)

    fix(schema)
    return schema


def _call(model, prompt, schema, reasoning):
    """API 한 번 호출 → (JSON 문자열, 토큰 사용량). 일시적 오류면 쉬었다가 다시 시도."""
    for attempt in range(6):
        try:
            if PROVIDER == "openai":
                return _call_openai(model, prompt, schema, reasoning)
            return _call_gemini(model, prompt, schema, reasoning)
        except Exception as e:
            if not _is_retryable(e) or attempt == 5:
                raise
            time.sleep(10 * (attempt + 1))


def _is_retryable(e):
    text = str(e)
    if "insufficient_quota" in text or "PerDay" in text:
        return False  # 잔액 부족·하루 한도는 기다려도 안 풀린다
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    return code in (429, 500, 502, 503, 504)


def _call_openai(model, prompt, schema, reasoning):
    resp = client().responses.create(
        model=model,
        input=prompt,
        reasoning={"effort": reasoning},
        text={"format": {"type": "json_schema", "name": "result",
                         "schema": _strict(schema), "strict": True}},
    )
    u = resp.usage
    thinking = u.output_tokens_details.reasoning_tokens or 0
    return resp.output_text, {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens - thinking,   # OpenAI 는 추론 토큰을 출력에 포함해서 센다
        "thinking_tokens": thinking,
    }


def _call_gemini(model, prompt, schema, reasoning):
    from google.genai import types
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=reasoning),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    resp = client().models.generate_content(model=model, contents=prompt, config=config)
    u = resp.usage_metadata
    return resp.text, {
        "input_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "thinking_tokens": u.thoughts_token_count or 0,
    }


def _add_usage(total, usage):
    for k, v in usage.items():
        total[k] = total.get(k, 0) + v


def generate_task(topic, medium, relationship):
    text, _ = _call(TASK_MODEL, task_prompt(topic, medium, relationship),
                    Task.model_json_schema(), TASK_REASONING)
    return Task.model_validate_json(text)


def grade_once(prompt, mode):
    """채점 1회. JSON 이 형식에 안 맞으면 한 번 더 요청하고, 그래도 안 되면 에러를 낸다."""
    usage = {}
    for attempt in range(2):
        text, u = _call(GRADER_MODEL, prompt, _grade_schema(mode), GRADER_REASONING)
        _add_usage(usage, u)
        try:
            return GradeResult.model_validate_json(text), usage
        except ValidationError:
            if attempt == 1:
                raise


def grade_samples(prompt, mode, n):
    """같은 프롬프트로 n번 동시에 채점 (ThreadPoolExecutor = 여러 호출을 병렬로 돌리는 도구)."""
    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda _: grade_once(prompt, mode), range(n)))
    samples = [r[0] for r in results]
    usage = {}
    for _, u in results:
        _add_usage(usage, u)
    return samples, usage


def grade(answer, task, mode, topic, medium, relationship, source="app", n_samples=None):
    """채점하고 다수결로 합친 Attempt 를 돌려준다 (저장은 호출한 쪽에서)."""
    n = n_samples or N_SAMPLES
    prompt = grade_prompt(mode, task, medium, relationship, answer)
    samples, usage = grade_samples(prompt, mode, n)
    combined = combine(answer, samples, codes_for_mode(mode))
    return Attempt(
        id=uuid.uuid4().hex[:12],
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        source=source,
        mode=mode,
        topic=topic,
        medium=medium,
        relationship=relationship,
        task=task,
        answer=answer,
        taxonomy_version=TAXONOMY_VERSION,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        model=GRADER_MODEL,
        thinking_level=GRADER_REASONING,
        usage=usage,
        **combined,
    )
