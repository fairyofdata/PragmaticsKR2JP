"""일본어 작문 코치 — Streamlit 화면.

실행: streamlit run app.py
"""

import os
import random

import streamlit as st
from dotenv import load_dotenv

from coach import store
from coach.prompts import TOPICS
from coach.prompts import PROMPT_VERSION
from coach.schemas import SCHEMA_VERSION
from coach.stats import filter_records, streak_days, summary_counts, top_types, version_mix
from coach.taxonomy import MODES, OUT_OF_MODE, TAXONOMY_VERSION, name_ko
from coach.verify import diff_html

load_dotenv()
st.set_page_config(page_title="일본어 작문 코치", page_icon="✍️", layout="centered")

# ---------- 사이드바 ----------
with st.sidebar:
    mode = st.radio("모드", list(MODES), format_func=lambda m: MODES[m])
    topic = st.selectbox("주제", list(TOPICS))
    st.divider()
    source = st.radio("요약에 쓸 기록", ["내 기록", "시연용 예시", "둘 다"], index=2)
    include_older = st.toggle("이전 버전 기록도 포함", value=False,
                              help="기본은 유형표·프롬프트·스키마·모델이 모두 현재와 같은 기록만 집계합니다. "
                                   "켜면 유형표만 같은 기록을 함께 집계하고, 섞인 버전 구성을 보여줍니다.")
    show_streak = st.toggle("연속 사용일 표시", value=False)


def load_records():
    records = []
    if source in ("내 기록", "둘 다"):
        records += store.load(store.DATA_FILE)
    if source in ("시연용 예시", "둘 다"):
        records += store.load(store.SAMPLES_FILE)
    return records


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
    st.caption(f"해석된 뜻: {r['intended_meaning_ko']}")

    in_mode = [e for e in r["errors"] if e["type"] != OUT_OF_MODE]
    out_mode = [e for e in r["errors"] if e["type"] == OUT_OF_MODE]
    if not r["errors"]:
        st.success("확정된 오류가 없습니다.")
    for e in in_mode:
        st.markdown(tag_line(e, r["n_samples"]))
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


tab_practice, tab_summary = st.tabs(["연습", "요약"])

# ---------- 연습 ----------
with tab_practice:
    key_name = "GEMINI_API_KEY" if os.getenv("LLM_PROVIDER") == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key_name):
        st.error(f"{key_name} 가 없습니다. .env.example 을 .env 로 복사해 키를 넣어 주세요.")

    if st.button("과제 받기", type="primary"):
        from coach import llm
        medium, relationship = random.choice(TOPICS[topic])
        with st.spinner("과제를 만드는 중..."):
            task = llm.generate_task(topic, medium, relationship)
        st.session_state.update(task=task, topic=topic, medium=medium,
                                relationship=relationship, result=None)

    task = st.session_state.get("task")
    if task:
        st.caption(f"{st.session_state.topic} · {st.session_state.medium} · "
                   f"상대: {st.session_state.relationship}")
        st.markdown(f"**상황** {task.situation_ko}")
        st.markdown(f"**과제** {task.instruction_ko}")
        answer = st.text_area("일본어로 쓰기", height=150)

        if st.button("채점", disabled=not answer.strip()):
            from coach import llm
            with st.spinner(f"{llm.N_SAMPLES}번 채점해서 합치는 중..."):
                attempt = llm.grade(answer, task, mode, st.session_state.topic,
                                    st.session_state.medium, st.session_state.relationship)
            store.append(attempt)
            st.session_state.result = attempt.model_dump()

    if st.session_state.get("result"):
        st.divider()
        show_result(st.session_state.result)

# ---------- 요약 ----------
with tab_summary:
    from coach import llm   # 현재 채점 모델 이름을 알기 위해 (API 호출은 하지 않음)
    all_records = load_records()
    current = {"taxonomy_version": TAXONOMY_VERSION, "prompt_version": PROMPT_VERSION,
               "schema_version": SCHEMA_VERSION, "model": llm.GRADER_MODEL}
    records = filter_records(all_records, mode, current, include_older)
    excluded = len(filter_records(all_records, mode, current, include_older=True)) - len(records)
    st.subheader(MODES[mode])
    st.caption(f"집계 기준: 유형표 {current['taxonomy_version']} · 프롬프트 {current['prompt_version']} · "
               f"스키마 {current['schema_version']} · 모델 {current['model']}"
               + (f" — 이전 버전 기록 {excluded}건 제외 (사이드바에서 포함 가능)" if excluded else ""))
    if include_older:
        mix = version_mix(records)
        if len(mix) > 1:
            parts = " / ".join(f"{p}·{s}·{m} {n}건" for (p, s, m), n in mix)
            st.warning(f"서로 다른 측정 도구 버전의 기록이 섞여 있습니다: {parts}")

    if show_streak:
        app_records = [r for r in all_records if r["source"] == "app"]  # 합성 예시는 제외
        st.metric("연속 사용일", f"{streak_days(app_records)}일")

    if not records:
        st.info("아직 이 모드의 기록이 없습니다.")
    else:
        c = summary_counts(records)
        col1, col2, col3 = st.columns(3)
        col1.metric("시도", c["attempts"])
        col2.metric("확정 오류", c["errors"] - c["out_of_mode"])
        col3.metric("오류 없는 시도", c["error_free"])
        st.caption(f"모드 밖 오류 {c['out_of_mode']} · 낮은 확신 {c['tentative']} · "
                   f"태그 없이 고쳐진 곳 {c['untagged_changes']} (모두 순위에서 제외)")

        st.markdown("### 자주 틀리는 유형 상위 5개")
        st.caption("순위 = 그 유형이 나온 시도의 수. 한 답에 같은 오류가 여러 번 있어도 1로 셉니다. "
                   "오류 위치는 안정적이지만 유형 이름은 경계에서 흔들릴 수 있어서(재현성 실험, README 참고), "
                   "유형마다 채점 일치도를 함께 보여줍니다.")
        for i, t in enumerate(top_types(records), start=1):
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
