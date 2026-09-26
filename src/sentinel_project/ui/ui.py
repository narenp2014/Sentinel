from __future__ import annotations

from uuid import uuid4

import streamlit as st
from fastapi import HTTPException
from openai import OpenAIError

from sentinel_project.agents.redteam import run_red_team_suite
from sentinel_project.models.model import Message, TargetRequest, TargetResponse
from sentinel_project.retrieval.policies import load_policy_documents
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

    tab1, tab2 = st.tabs(["Assistant", "Red Team"])

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
