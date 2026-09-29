"""일본어 작문 코치 — Streamlit 화면.

실행: streamlit run app.py
"""

import os
import random
import time
import uuid
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from coach import llm, store
from coach.corpus import (EXCLUDED_LABELS, LABELS, excluded_keys, frequent_patterns,
                          repeated_after_revision, revision_summary, tag_rows, target_candidates,
                          target_outcome, target_summary, unlabeled)
from coach.prompts import PROMPT_VERSION, TOPICS
from coach.schemas import SCHEMA_VERSION, Revision, RevisionCheck
from coach.stats import (filter_records, streak_days, summary_counts, tag_key, top_types,
                         version_mix, weekly_trend)
from coach.taxonomy import MODES, OUT_OF_MODE, TAXONOMY_VERSION, name_ko
from coach.verify import check_revision, diff_html, highlight_html, similarity, word_edits

load_dotenv()
st.set_page_config(page_title="일본어 작문 코치", page_icon="✍️", layout="centered")

INPUT_KINDS = {"generated": "앱이 낸 과제", "own_korean": "내 한국어 문장", "targeted": "약점 겨냥 연습"}
REVISION_STATUS = {"fixed": "고침", "unchanged": "그대로 (안 고침)", "changed": "다르게 고침 (다시 채점으로 확인)"}
TARGET_OUTCOME = {"repeated": "또 틀림", "used": "맞게 씀", "not_used": "이번 답에서 그 표현을 쓰지 않음"}
MEDIUMS = ["메일", "채팅", "구두"]
RELATIONSHIPS = sorted({rel for scenes in TOPICS.values() for _, rel in scenes})
# 자연스러운 문장이 교정문과 글자 기준으로 이보다 덜 비슷하면 '사실상 다시 쓴 글'로 보고 하이라이트하지 않는다
NATURAL_HINT_MIN_SIMILARITY = 0.6

# ---------- 사이드바 ----------
with st.sidebar:
    mode = st.radio("모드", list(MODES), format_func=lambda m: MODES[m])
    topic = st.selectbox("주제 (앱이 낸 과제일 때)", list(TOPICS))
    st.divider()
    source = st.radio("요약에 쓸 기록", ["내 기록", "시연용 예시", "둘 다"], index=2)
    include_older = st.toggle("이전 버전 기록도 포함", value=False,
                              help="기본은 측정 도구(유형표·채점 프롬프트·모델)가 모두 현재와 같은 기록만 집계합니다. "
                                   "켜면 유형표만 같은 기록을 함께 집계하고, 섞인 버전 구성을 보여줍니다.")
    show_streak = st.toggle("연속 사용일 표시", value=False)

labels = store.load_labels()


def load_records():
    records = []
    if source in ("내 기록", "둘 다"):
        records += store.load(store.DATA_FILE)
    if source in ("시연용 예시", "둘 다"):
        records += store.load(store.SAMPLES_FILE)
    return records


CURRENT = {"taxonomy_version": TAXONOMY_VERSION, "prompt_version": PROMPT_VERSION, "model": llm.GRADER_MODEL}


def split_records(all_records):
    """집계 대상(측정)과 약점 겨냥 연습을 나눈다. 겨냥 연습은 특정 오류를 유도하는 과제라서
    빈출 오답·상위 5개·추이에 넣으면 그 유형의 비율이 인위적으로 올라간다 (ADR 0013)."""
    measured = filter_records(all_records, mode, CURRENT, include_older)
    return ([r for r in measured if r.get("input_mode") != "targeted"],
            [r for r in measured if r.get("input_mode") == "targeted"])


def pattern_text(p):
    target = f" (… {p['governing']})" if p["governing"] else ""
    return f"{name_ko(p['type'])} · {p['edit']}{target}"


@st.cache_data(max_entries=8)
def build_rows(records, labels):
    """확정 태그를 코퍼스 행으로 펼친다 (형태소 분석이 들어가서 캐시한다)."""
    return tag_rows(records, labels)


def save_label(key, widget_key):
    """판정 버튼을 누르면 labels.jsonl 에 한 줄 추가한다 (다시 누르면 선택 해제 = 판정 취소)."""
    store.append_label(key, st.session_state[widget_key])


def label_control(key, where):
    """태그 하나의 판정 버튼. 같은 태그가 여러 화면에 나올 수 있어 위젯 키에 위치를 붙인다."""
    widget_key = f"label_{where}_{key}"
    st.segmented_control("판정", list(LABELS), format_func=LABELS.get, default=labels.get(key),
                         key=widget_key, on_change=save_label, args=(key, widget_key),
                         label_visibility="collapsed")


def tag_line(e, n):
    badge = " · 🇰🇷 직역 간섭" if e["kr_interference"] else ""
    level = "오류" if e["severity"] == "error" else "부자연"
    return (f"**[{name_ko(e['type'])}]** `{e['original']}` → `{e['corrected']}` "
            f"({level}, {e['votes']}/{n}회 일치{badge})  \n{e['explanation_ko']}")


def show_result(r):
    st.markdown("**교정 (확정된 오류만 반영)**")
    # s2 부터: 확정 태그만 원문에 적용해 코드가 만든 교정문. 아래 오류 목록과 항상 일치한다.
    corrected = r.get("confirmed_correction") or r["minimal_correction"]
    st.markdown(diff_html(r["answer"], corrected), unsafe_allow_html=True)
    if r.get("correction_source") == "sample_fallback":
        st.caption("확정 태그끼리 범위가 겹쳐 코드로 교정문을 만들 수 없어서, 채점 3회 중 하나의 교정문을 보여줍니다. "
                   "확정되지 않은 수정이 섞여 있을 수 있습니다.")
    elif not r.get("confirmed_correction"):
        st.caption("이전 형식의 기록입니다. 채점 3회 중 하나의 교정문이라 확정되지 않은 수정이 섞여 있을 수 있습니다.")
    st.markdown("**이 장면에서 자연스러운 문장** (참고, 채점 1회분의 다시 쓰기)")
    st.info(r["natural_version"])
    # 최소 교정에서는 넘겼지만 자연스러운 문장에서만 바꾼 곳 (예: その→あの). 오류로 확정된 게 아니라 집계에는 넣지 않는다.
    hints = word_edits(corrected, r["natural_version"])
    if hints and similarity(corrected, r["natural_version"]) >= NATURAL_HINT_MIN_SIMILARITY:
        with st.expander(f"표현 참고: 교정문과 자연스러운 문장이 다른 곳 {len(hints)}군데 (집계 제외)"):
            st.markdown(diff_html(corrected, r["natural_version"]), unsafe_allow_html=True)
            st.caption("오류로 확정되지는 않았지만, 이 장면이라면 원어민은 이렇게 쓸 수 있다는 차이입니다.")
    elif hints:
        st.caption("자연스러운 문장은 교정문을 크게 다시 쓴 것이라 차이 표시는 생략합니다.")
    st.caption(f"해석된 뜻: {r['intended_meaning_ko']}")

    in_mode = [e for e in r["errors"] if e["type"] != OUT_OF_MODE]
    out_mode = [e for e in r["errors"] if e["type"] == OUT_OF_MODE]
    if not r["errors"]:
        st.success("확정된 오류가 없습니다.")
    if in_mode:
        st.caption("지적마다 판정해 주세요. '실수'와 '지적이 틀림'은 빈출 오답에서 빠지고, "
                   "'지적이 틀림'은 도구의 정확도를 재는 데 쓰입니다.")
    rows = {row["key"]: row for row in build_rows([r], labels)}
    for e in in_mode:
        key = tag_key(r["id"], e)
        with st.container(border=True):
            st.markdown(tag_line(e, r["n_samples"]))
            if rows.get(key, {}).get("ime_candidate"):
                st.caption("읽기가 같은 수정입니다 → IME 변환 실수 후보. '몰랐음'으로 판정하지 않으면 빈출 오답에서 빠집니다.")
            label_control(key, "result")
    if out_mode:
        with st.expander(f"모드 밖 오류 {len(out_mode)}건 (집계 제외)"):
            for e in out_mode:
                st.markdown(tag_line(e, r["n_samples"]))
    if r["tentative_errors"]:
        with st.expander(f"참고: 낮은 확신 {len(r['tentative_errors'])}건 (과반 미달, 집계 제외)"):
            for e in r["tentative_errors"]:
                st.markdown(tag_line(e, r["n_samples"]))
    for m in r.get("merged_tags", []):
        edits = ", ".join(f"`{e['original']}`→`{e['corrected']}`" for e in m["edits"])
        st.warning(f"태그 하나에 수정이 {len(m['edits'])}개 합쳐져 있습니다: {edits} "
                   f"(붙은 유형은 [{name_ko(m['type'])}] 하나뿐 — 나머지 수정도 따로 확인하세요)")
    if r["untagged_changes"]:
        changes = ", ".join(f"`{c['original']}`→`{c['corrected']}`" for c in r["untagged_changes"])
        st.warning(f"태그 없이 고쳐진 곳이 있습니다 (설명 누락): {changes}")
    if r.get("ambiguous_quotes"):
        st.warning(f"같은 글자가 답에 여러 번 나와서 위치를 하나로 정하지 못한 지적이 {r['ambiguous_quotes']}건 있습니다. "
                   "표시된 위치가 실제 오류 위치와 다를 수 있습니다.")
    if r["dropped_quotes"]:
        st.caption(f"원문에 없는 인용이라 버린 태그: {r['dropped_quotes']}건")


def confirmed_tags(r):
    return [e for e in r["errors"] if "start" in e]


def revision_entry(r):
    """결과 아래의 '고쳐 쓰기' 시작 버튼."""
    if not confirmed_tags(r):
        return
    st.divider()
    st.markdown("**고쳐 쓰기**")
    st.caption("교정을 가리고 틀린 곳만 표시한 채로 다시 써 봅니다. 교정은 읽기만 할 때보다 직접 고쳐 쓸 때 오래 남습니다. "
               "고쳐 쓴 답은 피드백을 본 뒤라 집계에는 넣지 않습니다.")
    if st.button("교정 가리고 다시 쓰기"):
        st.session_state.update(revising=r["id"], revision_text=r["answer"],
                                revision_started=time.time(), revision=None)
        st.rerun()


def revision_view(r):
    """고쳐 쓰기 화면: 교정은 가리고 틀린 자리와 유형만 보여준다 → 확인(코드, 무료) → 선택적으로 다시 채점."""
    tags = confirmed_tags(r)
    st.markdown("**고쳐 쓰기** — 교정은 가려 두었습니다. 표시된 곳을 스스로 고쳐 보세요.")
    st.markdown(highlight_html(r["answer"], [(e["start"], e["end"]) for e in tags]), unsafe_allow_html=True)
    st.caption("표시된 곳의 유형: " + " · ".join(f"{i}. {name_ko(e['type'])}" for i, e in enumerate(tags, 1)))
    text = st.text_area("고쳐 쓴 답", key="revision_text", height=150)

    if st.button("확인", type="primary", disabled=not text.strip()):
        statuses = check_revision(r["answer"], text, tags)
        rev = Revision(
            id=uuid.uuid4().hex[:12], parent_id=r["id"],
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"), text=text,
            duration_sec=int(time.time() - st.session_state.get("revision_started", time.time())),
            checks=[RevisionCheck(key=tag_key(r["id"], e), type=e["type"], original=e["original"],
                                  corrected=e["corrected"], status=s) for e, s in zip(tags, statuses)],
            schema_version=SCHEMA_VERSION)
        store.append_revision(rev)
        st.session_state.revision = rev.model_dump()

    rev = st.session_state.get("revision")
    if rev and rev["parent_id"] == r["id"]:
        st.markdown("**확인 결과** (코드로 확인, 교정은 이제 보여 드립니다)")
        for c in rev["checks"]:
            st.markdown(f"- {REVISION_STATUS[c['status']]} · [{name_ko(c['type'])}] "
                        f"`{c['original']}` → 교정 `{c['corrected']}`")
        if not rev["regraded"]:
            st.caption("'다르게 고침'은 다른 맞는 표현일 수도, 여전히 틀렸을 수도 있습니다. "
                       "다시 채점하면 고쳐 쓰면서 새로 생긴 오류까지 확인합니다.")
            if st.button(f"다시 채점 ({llm.N_SAMPLES}회, 약 $0.04)"):
                with st.spinner("다시 채점하는 중..."):
                    regrade = llm.grade(rev["text"], st.session_state.task, mode, st.session_state.topic,
                                        st.session_state.medium, st.session_state.relationship)
                repeated = repeated_after_revision(r, [e.model_dump() for e in regrade.errors], rev["text"])
                updated = Revision(**{**rev, "regraded": True, "regrade_errors": regrade.errors,
                                      "repeated_patterns": repeated, "regrade_model": regrade.model,
                                      "regrade_prompt_version": regrade.prompt_version, "usage": regrade.usage})
                store.append_revision(updated)            # 같은 id 로 새 줄 (마지막 줄이 이긴다)
                st.session_state.revision = updated.model_dump()
                st.rerun()
        else:
            if rev["repeated_patterns"]:
                st.warning("고쳐 쓰고도 또 틀린 패턴 — 실수가 아니라 잘못 알고 있을 가능성이 큽니다: "
                           + ", ".join(f"`{pattern_text(p)}`" for p in rev["repeated_patterns"]))
            others = [e for e in rev["regrade_errors"] if e["type"] != OUT_OF_MODE]
            if others:
                st.markdown("다시 채점에서 나온 오류")
                for e in others:
                    st.markdown(tag_line(e, llm.N_SAMPLES))
            else:
                st.success("다시 채점에서 확정된 오류가 없습니다.")

    if st.button("교정 보기 (고쳐 쓰기 끝내기)"):
        st.session_state.revising = None
        st.rerun()


def start_task(task, topic_name, medium, relationship, input_mode, source_ko="", target=None):
    """새 과제를 시작한다. 이전 답·결과·고쳐 쓰기는 지우고, 걸린 시간을 재기 시작한다."""
    st.session_state.update(task=task, topic=topic_name, medium=medium, relationship=relationship,
                            input_mode=input_mode, source_ko=source_ko, target=target,
                            started_at=time.time(), result=None, answer_text="",
                            revising=None, revision=None)


tab_practice, tab_summary = st.tabs(["연습", "요약"])

# ---------- 연습 ----------
with tab_practice:
    key_name = "GEMINI_API_KEY" if os.getenv("LLM_PROVIDER") == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key_name):
        st.error(f"{key_name} 가 없습니다. .env.example 을 .env 로 복사해 키를 넣어 주세요.")

    input_kind = st.segmented_control("입력 방식", list(INPUT_KINDS), format_func=INPUT_KINDS.get,
                                      default="generated", required=True, key="input_kind")

    if input_kind == "generated":
        if st.button("과제 받기", type="primary"):
            medium, relationship = random.choice(TOPICS[topic])
            with st.spinner("과제를 만드는 중..."):
                task = llm.generate_task(topic, medium, relationship)
            start_task(task, topic, medium, relationship, "generated")
    elif input_kind == "own_korean":
        st.caption("사전·번역기 없이 평소처럼 옮겨 주세요. 그래야 실제 약점이 기록됩니다.")
        source_ko = st.text_area("일본어로 옮길 한국어 문장", height=100, key="source_ko_input")
        col1, col2 = st.columns(2)
        medium = col1.selectbox("매체", MEDIUMS)
        relationship = col2.selectbox("상대", RELATIONSHIPS)
        if st.button("이 문장으로 시작", type="primary", disabled=not source_ko.strip()):
            start_task(llm.own_korean_task(source_ko.strip(), medium, relationship),
                       "내 문장", medium, relationship, "own_korean", source_ko.strip())
    else:  # targeted
        st.caption("반복해서 틀리는 패턴을 쓰게 되는 과제를 받습니다. 겨냥 연습은 일부러 약점을 유도하므로 "
                   "빈출 오답·상위 5개·추이에는 넣지 않고, 요약 탭에 따로 결과를 보여줍니다.")
        measured, _ = split_records(load_records())
        candidates = target_candidates(build_rows(measured, labels))
        if not candidates:
            st.info("겨냥할 패턴이 아직 없습니다. 빈출 오답이 생기거나 '몰랐음'으로 판정한 지적이 있으면 나타납니다.")
        else:
            idx = st.selectbox("겨냥할 패턴", range(len(candidates)),
                               format_func=lambda i: f"{pattern_text(candidates[i])} — {candidates[i]['attempts']}번의 시도")
            col1, col2 = st.columns(2)
            medium = col1.selectbox("매체", MEDIUMS, key="target_medium")
            relationship = col2.selectbox("상대", RELATIONSHIPS, key="target_relationship")
            if st.button("겨냥 과제 받기", type="primary"):
                target = {k: candidates[idx][k] for k in ("type", "edit", "governing")}
                with st.spinner("과제를 만드는 중..."):
                    task = llm.generate_targeted_task(target, medium, relationship)
                start_task(task, "약점 겨냥", medium, relationship, "targeted", target=target)

    task = st.session_state.get("task")
    if task:
        st.caption(f"{st.session_state.topic} · {st.session_state.medium} · "
                   f"상대: {st.session_state.relationship}")
        st.markdown(f"**상황** {task.situation_ko}")
        st.markdown(f"**과제** {task.instruction_ko}")
        answer = st.text_area("일본어로 쓰기", height=150, key="answer_text")

        if st.button("채점", disabled=not answer.strip()):
            duration = int(time.time() - st.session_state.get("started_at", time.time()))
            with st.spinner(f"{llm.N_SAMPLES}번 채점해서 합치는 중..."):
                attempt = llm.grade(answer, task, mode, st.session_state.topic,
                                    st.session_state.medium, st.session_state.relationship,
                                    input_mode=st.session_state.input_mode,
                                    source_ko=st.session_state.source_ko, duration_sec=duration,
                                    target=st.session_state.get("target"))
            store.append(attempt)
            st.session_state.update(result=attempt.model_dump(), revising=None, revision=None)

    result = st.session_state.get("result")
    if result:
        st.divider()
        if st.session_state.get("revising") == result["id"]:
            revision_view(result)
        else:
            if result.get("target"):
                outcome = target_outcome(result, result["target"])
                box = st.error if outcome == "repeated" else st.success if outcome == "used" else st.info
                box(f"겨냥한 패턴 `{pattern_text(result['target'])}`: {TARGET_OUTCOME[outcome]}")
            show_result(result)
            revision_entry(result)

# ---------- 요약 ----------
with tab_summary:
    all_records = load_records()
    records, targeted = split_records(all_records)
    excluded = len(filter_records(all_records, mode, CURRENT, include_older=True)) - len(records) - len(targeted)
    st.subheader(MODES[mode])
    st.caption(f"집계 기준 (측정 도구): 유형표 {CURRENT['taxonomy_version']} · 채점 프롬프트 {CURRENT['prompt_version']} · "
               f"모델 {CURRENT['model']}"
               + (f" — 이전 버전 기록 {excluded}건 제외 (사이드바에서 포함 가능)" if excluded else "")
               + (f" · 약점 겨냥 연습 {len(targeted)}건은 아래 따로" if targeted else ""))
    if include_older:
        mix = version_mix(records)
        if len(mix) > 1:
            parts = " / ".join(f"{p}·{m} {n}건" for (p, m), n in mix)
            st.warning(f"서로 다른 측정 도구 버전의 기록이 섞여 있습니다: {parts}")

    if show_streak:
        app_records = [r for r in all_records if r["source"] == "app"]  # 합성 예시는 제외
        st.metric("연속 사용일", f"{streak_days(app_records)}일")

    if not records:
        st.info("아직 이 모드의 기록이 없습니다.")
    else:
        rows = build_rows(records, labels)
        c = summary_counts(records)
        col1, col2, col3 = st.columns(3)
        col1.metric("시도", c["attempts"])
        col2.metric("확정 오류", c["errors"] - c["out_of_mode"])
        col3.metric("오류 없는 시도", c["error_free"])
        n_labeled_out = sum(1 for row in rows if row["label"] in EXCLUDED_LABELS)
        n_ime_out = sum(1 for row in rows if row["excluded"] and row["label"] not in EXCLUDED_LABELS)
        st.caption(f"모드 밖 오류 {c['out_of_mode']} · 낮은 확신 {c['tentative']} · "
                   f"태그 없이 고쳐진 곳 {c['untagged_changes']} · '실수/지적이 틀림' 판정 {n_labeled_out} · "
                   f"변환 실수 후보 {n_ime_out} (모두 순위에서 제외)")

        # --- 빈출 오답 ---
        st.markdown("### 빈출 오답")
        st.caption("같은 패턴이 서로 다른 시도에서 2번 이상 나온 것. 한 번뿐인 오류(오타일 수 있음)는 오르지 않습니다. "
                   "조사 오류는 걸리는 동사까지 묶습니다.")
        only_unknown = st.toggle("'몰랐음'으로 판정한 것만 보기", value=False)
        patterns = frequent_patterns(rows, only_unknown=only_unknown)
        if not patterns:
            st.info("아직 2번 이상 반복된 패턴이 없습니다. 기록이 쌓이면 나타납니다.")
        for p in patterns:
            with st.container(border=True):
                target = f" (… {p['governing']})" if p["governing"] else ""
                st.markdown(f"**{name_ko(p['type'])}** · `{p['edit']}`{target} — {p['attempts']}번의 시도에서 {p['count']}건")
                judged = ", ".join(f"{LABELS.get(k, '미판정')} {v}" for k, v in sorted(p["labels"].items()))
                st.caption(f"판정: {judged}")
                for ex in p["examples"]:
                    st.markdown(f"`{ex['original']}` → `{ex['corrected']}` · {ex['topic']}  \n{ex['explanation_ko']}")
                    st.caption(ex["answer"])

        # --- 유형 상위 5개 ---
        st.markdown("### 자주 틀리는 유형 상위 5개")
        st.caption("순위 = 그 유형이 나온 시도의 수. 한 답에 같은 오류가 여러 번 있어도 1로 셉니다. "
                   "오류 위치는 안정적이지만 유형 이름은 경계에서 흔들릴 수 있어서(재현성 실험, README 참고), "
                   "유형마다 채점 일치도를 함께 보여줍니다.")
        for i, t in enumerate(top_types(records, exclude_keys=excluded_keys(rows)), start=1):
            label = (f"{i}. {t['name_ko']} — {t['attempts_with']}/{c['attempts']}회 시도 "
                     f"({t['share']:.0%}), 확정 {t['count']}건 · 낮은 확신 {t['tentative']}건")
            with st.expander(label, expanded=(i == 1)):
                st.caption(f"신뢰도: 확정 {t['count']}건 중 전원 일치 {t['unanimous']}건, "
                           f"평균 일치 {t['mean_vote_share']:.0%} · "
                           f"과반 미달로 순위에서 뺀 건수 {t['tentative']} · 직역 간섭 {t['kr_interference']}건")
                for ex in t["examples"]:
                    st.markdown(f"`{ex['original']}` → `{ex['corrected']}` · {ex['topic']}  \n"
                                f"{ex['explanation_ko']}")
                    st.caption(ex["answer"])

        # --- 주간 추이 ---
        codes = [t["code"] for t in top_types(records, exclude_keys=excluded_keys(rows))]
        trend = weekly_trend(records, codes, excluded_keys(rows))
        st.markdown("### 주간 추이")
        st.caption("주마다 '그 유형이 나온 시도의 비율'입니다. 시도 수가 주마다 달라서 건수 대신 비율로 봅니다. "
                   "시도가 적은 주의 비율은 크게 흔들리니 시도 수와 함께 보세요. 실수·변환 실수 후보는 빠져 있습니다.")
        if len(trend) < 2:
            st.info("2주 이상 기록이 쌓이면 변화를 볼 수 있습니다.")
        if trend and codes:
            table = [{"주": t["week"], "시도": t["attempts"],
                      "걸린 시간(중앙값, 초)": t["median_sec"],
                      **{name_ko(code): t["rates"][code] for code in codes}} for t in trend]
            st.dataframe(table, hide_index=True,
                         column_config={name_ko(code): st.column_config.NumberColumn(format="percent")
                                        for code in codes})

        # --- 고쳐 쓰기에서 드러난 것 ---
        rev_summary = revision_summary(rows, list(store.load_revisions().values()))
        if rev_summary:
            st.markdown("### 고쳐 쓰기에서 드러난 것")
            st.caption("틀린 자리를 알려 줬는데도 안 고쳐지거나, 다시 채점에서 또 틀린 패턴은 실수가 아니라 "
                       "잘못 알고 있을 가능성이 큽니다. 고쳐 쓰기 자체는 집계에 넣지 않습니다.")
            st.dataframe([{"패턴": pattern_text(p), "고침": p["fixed"], "그대로": p["unchanged"],
                           "다르게 고침": p["changed"], "다시 채점에서 또 틀림": p["repeated"]}
                          for p in rev_summary], hide_index=True)

        # --- 판정 대기 ---
        todo = unlabeled(rows)
        with st.expander(f"아직 판정하지 않은 지적 {len(todo)}건 (최근 것부터 최대 20건)"):
            for row in todo:
                with st.container(border=True):
                    st.markdown(f"**[{name_ko(row['type'])}]** `{row['original']}` → `{row['corrected']}` · "
                                f"{row['topic']}  \n{row['explanation_ko']}")
                    st.caption(row["answer"])
                    label_control(row["key"], "summary")

    # --- 약점 겨냥 연습 (집계와 분리) ---
    if targeted:
        st.markdown("### 약점 겨냥 연습")
        st.caption("겨냥한 패턴을 이번엔 맞게 썼는지. '그 표현을 쓰지 않음'은 피해 간 것이라 맞게 쓴 것으로 치지 않습니다. "
                   "이 연습은 특정 오류를 유도하므로 위의 빈출 오답·상위 5개·추이에는 넣지 않았습니다.")
        st.dataframe([{"패턴": pattern_text(t), "시도": t["attempts"], "맞게 씀": t["used"],
                       "또 틀림": t["repeated"], "쓰지 않음": t["not_used"]} for t in target_summary(targeted)],
                     hide_index=True)
