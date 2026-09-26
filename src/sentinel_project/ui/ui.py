from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import uuid4

import httpx
import streamlit as st
from fastapi import HTTPException
from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from sentinel_project.agents.redteam import run_red_team_suite
from sentinel_project.attacks.taxonomy import CATEGORIES
from sentinel_project.evaluation.metrics import inter_rater_agreement, summarize_labels
from sentinel_project.models.model import Message, TargetRequest, TargetResponse
from sentinel_project.orchestrator import Orchestrator
from sentinel_project.retrieval.policies import load_policy_documents
from sentinel_project.settings import settings
from sentinel_project.storage.scan_store import ScanStore
from sentinel_project.target.target_app import target


def run_assistant_query(
    prompt: str,
    mode: str,
    session_id: str,
    hardened: bool = False,
) -> TargetResponse:
    """Run a prompt through the same target workflow used by the API."""
    request = TargetRequest(
        conversation=[Message(role="user", content=prompt)],
        mode=mode,
        hardened=hardened,
        session_id=session_id,
    )
    return target(request)


def render_dashboard() -> None:
    """Render the HR assistant tester and red-team checks."""
    st.title("Sentinel HR Policy Assistant")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Assistant", "Red Team", "Scans and findings", "Human labels", "Judge metrics"]
    )

    with tab1:
        session_id = st.session_state.setdefault("session_id", f"ui-{uuid4().hex}")
        mode = st.segmented_control(
            "Mode",
            options=["RAG", "Agentic"],
            default="RAG",
        ).lower()
        hardened = st.toggle(
            "Hardened safeguards",
            help="Filter common prompt-injection attempts and remove injected instructions from retrieved policy text.",
        )
        prompt = st.text_area(
            "Question or context",
            height=180,
            placeholder="Ask a question about an HR policy...",
        )

        if st.button("Execute", type="primary", disabled=not prompt.strip()):
            try:
                result = run_assistant_query(prompt.strip(), mode, session_id, hardened)
                st.session_state["assistant_output"] = result.output
                st.session_state["assistant_metadata"] = {
                    "retrieved_doc_ids": result.retrieved_doc_ids,
                    "retrieved_chunk_ids": result.retrieved_chunk_ids,
                    "retrieval_ranks": result.retrieval_ranks,
                    "verdict": result.usage.get("verdict", "unknown"),
                    "policy_violated": result.usage.get("policy_violated", []),
                    "tool_calls": result.tool_calls,
                }
                st.session_state.pop("assistant_error", None)
            except (HTTPException, OpenAIError) as exc:
                st.session_state["assistant_error"] = str(exc)

        if st.session_state.get("assistant_error"):
            st.error(st.session_state["assistant_error"])

        st.text_area(
            "Assistant response",
            value=st.session_state.get("assistant_output", ""),
            height=220,
            disabled=True,
        )

        metadata = st.session_state.get("assistant_metadata")
        if metadata:
            with st.expander("Response details"):
                st.write(f"Verdict: {metadata['verdict']}")
                st.write(f"Policies flagged: {', '.join(metadata['policy_violated']) or 'None'}")
                st.write(f"Retrieved policies: {', '.join(metadata['retrieved_doc_ids']) or 'None'}")
                st.write(f"Retrieved chunk ranks: {metadata['retrieval_ranks']}")
                for call in metadata["tool_calls"]:
                    st.write(f"Tool: {call.name}; result: {call.result}")

    with tab2:
        st.subheader("Built-in red-team prompts")
        suite = run_red_team_suite()
        for item in suite:
            st.markdown(f"### {item['prompt']}")
            st.write(item["verdict"])

        st.subheader("Loaded policy dataset")
        for doc in load_policy_documents():
            st.write(f"- {doc['title']}: {doc['text']}")

    store = ScanStore(settings.database_url)

    with tab3:
        st.subheader("Run a red-team scan")
        with st.form("scan_launcher"):
            budget = st.number_input("Attempt budget", min_value=1, max_value=2000, value=20, step=1)
            planner = st.selectbox("Planner", ["uniform", "smart"])
            categories = st.multiselect(
                "Attack categories",
                options=list(CATEGORIES),
                default=list(CATEGORIES),
            )
            hardened_scan = st.toggle("Scan hardened target", key="scan_hardened")
            max_cost = st.number_input("Estimated spend limit (USD)", min_value=0.01, value=2.0, step=0.25)
            start_scan = st.form_submit_button("Start scan", type="primary")
        if start_scan:
            try:
                with st.status("Running target scan", expanded=True) as status:
                    if not categories:
                        st.error("Select at least one attack category.")
                        st.stop()
                    result = asyncio.run(
                        Orchestrator(max_cost_usd=max_cost).run_scan(
                            int(budget),
                            planner_strategy=planner,
                            categories=categories,
                            hardened=hardened_scan,
                        )
                    )
                    status.update(label="Scan complete", state="complete")
                st.session_state["last_scan_result"] = result
            except (HTTPException, OpenAIError, httpx.HTTPError, ValueError, RuntimeError, SQLAlchemyError) as exc:
                st.error(f"Scan failed: {exc}")
        if st.session_state.get("last_scan_result"):
            st.json(st.session_state["last_scan_result"])

        st.subheader("Previous scans")
        scan_rows = store.scans()
        if scan_rows:
            st.dataframe(scan_rows, hide_index=True)
            st.subheader("Findings")
            findings = store.findings()
            if findings:
                st.dataframe(findings, hide_index=True)
                trace_rows = store.label_queue()
                trace_by_id = {row["attempt_id"]: row for row in trace_rows}
                for finding in findings:
                    with st.expander(f"Trace evidence: {finding['finding_id']} ({finding['severity']})"):
                        for attempt_id in finding["attempt_ids"]:
                            trace_row = trace_by_id.get(attempt_id)
                            if trace_row:
                                st.write(f"{attempt_id} | {trace_row['category']}")
                                st.json(trace_row["trace"])
            else:
                st.caption("No findings recorded yet.")
        else:
            st.caption("No scans have been run yet.")

    with tab4:
        st.subheader("Review a trace")
        scans = store.scans()
        selected_scan = None
        labeler_id = st.text_input("Your reviewer ID", key="labeler_id", placeholder="Reviewer 1")
        reviewer_ids_text = st.text_input(
            "Five reviewer IDs for this sample",
            key="reviewer_ids",
            placeholder="reviewer-1, reviewer-2, reviewer-3, reviewer-4, reviewer-5",
        )
        if scans:
            selected_scan_id = st.selectbox(
                "Scan to label",
                options=[row["scan_id"] for row in scans],
                format_func=lambda scan_id: next(
                    f"{row['started_at']} | {row['status']} | {scan_id}"
                    for row in scans
                    if row["scan_id"] == scan_id
                ),
            )
            selected_scan = next(row for row in scans if row["scan_id"] == selected_scan_id)
            with st.form("label_sample_form"):
                sample_size = st.number_input("Trace sample size", min_value=1, max_value=200, value=200)
                calibration_size = st.number_input("Shared calibration traces", min_value=1, max_value=50, value=50)
                prepare_sample = st.form_submit_button("Prepare labeling sample")
            if prepare_sample:
                reviewer_ids = [value.strip() for value in reviewer_ids_text.split(",") if value.strip()]
                try:
                    store.prepare_label_sample(
                        selected_scan_id,
                        size=int(sample_size),
                        calibration_size=int(calibration_size),
                        labeler_ids=reviewer_ids,
                    )
                    st.success("Saved a reproducible sample. All reviewers share the calibration subset; remaining traces are split among them.")
                except ValueError as exc:
                    st.error(str(exc))

        progress = store.calibration_progress(scan_id=selected_scan["scan_id"]) if selected_scan else {"attempts": 0, "completed": 0}
        if progress.get("prepared"):
            st.caption(
                f"Shared calibration set: {progress['completed']}/{progress['attempts']} traces have labels from all five reviewers."
            )
        queue = (
            store.label_queue(
                selected_scan["scan_id"],
                labeler_id=labeler_id.strip() or None,
            )
            if selected_scan
            else []
        )
        if queue:
            selected_id = st.selectbox(
                "Attempt",
                options=[row["attempt_id"] for row in queue],
                format_func=lambda attempt_id: next(
                    f"{row['attempt_id']} | {row['category']} | judge: {row['judge_verdict']}"
                    for row in queue
                    if row["attempt_id"] == attempt_id
                ),
            )
            selected = next(row for row in queue if row["attempt_id"] == selected_id)
            if selected["calibration"]:
                st.info("Calibration trace: all five reviewers label this same trace independently.")
            trace_col, label_col = st.columns(2)
            with trace_col:
                st.write("Conversation")
                st.json(selected["attempt"])
                st.write("Target trace")
                st.json(selected["trace"])
            with label_col:
                policies = st.text_input(
                    "Policy IDs",
                    placeholder="P1, P2",
                    key=f"label_policies_{selected_id}",
                )
                evidence = st.text_area(
                    "Exact evidence span",
                    key=f"label_evidence_{selected_id}",
                )
                notes = st.text_area(
                    "Reviewer notes",
                    key=f"label_notes_{selected_id}",
                )
                st.caption("Keyboard shortcuts: B = breach, D = defended, N = not delivered, A = ambiguous.")
                verdict_actions = (
                    ("Breach", "breach", "B"),
                    ("Defended", "defended", "D"),
                    ("Not delivered", "not_delivered", "N"),
                    ("Ambiguous", "ambiguous", "A"),
                )
                action_clicked = None
                with st.container(horizontal=True, wrap=True):
                    for label, verdict_value, shortcut in verdict_actions:
                        if st.button(
                            label,
                            key=f"save_{verdict_value}_{selected_id}",
                            shortcut=shortcut,
                            type="primary" if verdict_value == "breach" else "secondary",
                        ):
                            action_clicked = verdict_value

                if action_clicked:
                    if not labeler_id.strip():
                        st.error("Enter a labeler ID before saving.")
                    elif action_clicked == "breach" and not evidence.strip():
                        st.error("A breach label requires an exact evidence quote.")
                    elif action_clicked == "breach" and evidence not in selected["trace"].get("response", ""):
                        st.error("Evidence must appear exactly in the target response.")
                    else:
                        store.save_label(
                            selected_id,
                            labeler_id.strip(),
                            action_clicked,
                            policies=[value.strip() for value in policies.split(",") if value.strip()],
                            evidence_span=evidence or None,
                            notes=notes,
                        )
                        st.success(f"Saved {action_clicked} label.")
        else:
            st.caption("No traces are available for labeling. Run a scan first.")

    with tab5:
        st.subheader("Judge versus human labels")
        label_rows = store.labels_for_metrics()
        if label_rows:
            st.json(summarize_labels(label_rows))
            by_attempt: dict[str, dict[str, str]] = defaultdict(dict)
            for row in label_rows:
                by_attempt[row["attempt_id"]][row["labeler_id"]] = row["human_verdict"]
            labelers = sorted({row["labeler_id"] for row in label_rows})
            shared_attempts = [
                attempt_id
                for attempt_id, labels in by_attempt.items()
                if all(labeler in labels for labeler in labelers)
            ]
            if len(labelers) >= 2 and shared_attempts:
                label_sets = [
                    [by_attempt[attempt_id][labeler] for attempt_id in shared_attempts]
                    for labeler in labelers
                ]
                st.metric(
                    "Mean pairwise human agreement",
                    f"{inter_rater_agreement(label_sets):.1%}",
                )
                st.caption(f"Calculated on {len(shared_attempts)} traces labeled by all {len(labelers)} reviewers.")
        else:
            st.caption("Metrics appear after human labels are recorded.")
