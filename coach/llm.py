"""Gemini 호출은 이 파일에만 둔다. 제공자를 바꿀 때는 이 파일만 고친다.

설정은 환경변수(.env)로:
  GEMINI_API_KEY   (필수)
  GRADER_MODEL     채점 모델   (기본 gemini-3.8-flash)
  TASK_MODEL       출제 모델   (기본 gemini-3.1-flash-lite)
  GRADER_THINKING  채점 모델의 thinking_level (기본 low)
  N_SAMPLES        같은 답을 몇 번 채점해 다수결할지 (기본 3)

temperature 는 건드리지 않는다. Gemini 3 공식 문서가 기본값 1.0 유지를 강하게 권장하고,
낮추면 반복·성능 저하가 생길 수 있다고 적고 있다. 흔들림은 다수결로 다룬다.
"""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from .prompts import PROMPT_VERSION, grade_prompt, task_prompt
from .schemas import SCHEMA_VERSION, Attempt, GradeResult, Task
from .taxonomy import TAXONOMY_VERSION, codes_for_mode
from .voting import combine

load_dotenv()

GRADER_MODEL = os.getenv("GRADER_MODEL", "gemini-3.8-flash")
TASK_MODEL = os.getenv("TASK_MODEL", "gemini-3.1-flash-lite")
GRADER_THINKING = os.getenv("GRADER_THINKING", "low")
N_SAMPLES = int(os.getenv("N_SAMPLES", "3"))

_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client()  # GEMINI_API_KEY 를 환경변수에서 읽는다
    return _client


def _grade_schema(mode):
    """GradeResult 의 JSON 스키마에 '이 모드에서 쓸 수 있는 유형 코드'를 enum 으로 넣는다."""
    schema = GradeResult.model_json_schema()
    schema["$defs"]["ErrorTag"]["properties"]["type"]["enum"] = codes_for_mode(mode)
    return schema


def _call(model, prompt, schema, thinking_level):
    """API 한 번 호출. 일시적 오류(429 한도 초과, 5xx)면 잠깐 쉬고 최대 4번까지 다시 시도."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
    )
    for attempt in range(4):
        try:
            resp = client().models.generate_content(model=model, contents=prompt, config=config)
            return resp.text, _usage(resp)
        except errors.APIError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def _usage(resp):
    u = resp.usage_metadata
    return {
        "input_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "thinking_tokens": u.thoughts_token_count or 0,
    }


def _add_usage(total, usage):
    for k, v in usage.items():
        total[k] = total.get(k, 0) + v


def generate_task(topic, medium, relationship):
    text, _ = _call(TASK_MODEL, task_prompt(topic, medium, relationship),
                    Task.model_json_schema(), "low")
    return Task.model_validate_json(text)


def grade_once(prompt, mode):
    """채점 1회. JSON 이 형식에 안 맞으면 한 번 더 요청하고, 그래도 안 되면 에러를 낸다."""
    usage = {}
    for attempt in range(2):
        text, u = _call(GRADER_MODEL, prompt, _grade_schema(mode), GRADER_THINKING)
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
        thinking_level=GRADER_THINKING,
        usage=usage,
        **combined,
    )
