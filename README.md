# Sentinel Project

This repository is a capstone project focused on evaluating and hardening an LLM-based HR assistant against policy violations.

## Project goal

Build a small system that can:

- accept a user conversation request,
- route a request to either RAG or agentic mode,
- retrieve relevant policy documents,
- evaluate whether the model output violates internal policies,
- record attempts, verdicts, and evidence for analysis.

## Current structure

- `src/sentinel_project/models/` contains the core Pydantic models for requests, responses, attempts, and verdicts.
- `src/sentinel_project/target/` contains the target system prompt and runnable target app.
- `src/sentinel_project/agents/` contains agent and red-team workflows.
- `src/sentinel_project/retrieval/` contains policy retrieval and dataset loading.
- `src/sentinel_project/evaluation/` contains policy evaluation logic.
- `src/sentinel_project/storage/` contains SQLite persistence services.
- `src/sentinel_project/api/` contains the HTTP API.
- `src/sentinel_project/ui/` contains the Streamlit dashboard.
- `src/sentinel_project/settings.py` loads environment-backed configuration.
- `src/sentinel_project/app.py` mounts the API under a top-level app.

## Local setup

1. Create and activate a virtual environment with `uv`.
2. Install dependencies with `uv sync`.
3. Add environment values to a `.env` file based on `.env.example`.
4. Run tests with `uv run pytest -q`.
5. Start the API with `uv run uvicorn sentinel_project.app:app --reload`.

## Assistant API and retrieval

```powershell
uv run uvicorn sentinel_project.target.target_app:app --reload
```

The target exposes `POST /chat` (`/target` remains as a compatibility alias),
`/health`, and `/target/prompt`. Requests use `TargetRequest` and responses use
`TargetResponse`.

Policies from `src/sentinel_project/docs/policies.json` are chunked on sentence
boundaries at up to 500 characters, with one-sentence overlap. Long individual
sentences are split at word boundaries. Chroma's default local embedding function
indexes the chunks in a dedicated `sentinel_hr_policy_chunks_v1` collection under
`CHROMA_PATH`; the four nearest chunks are returned with stable chunk IDs and
1-based ranks. The first indexing run may download Chroma's default embedding
model. Existing collections are not deleted.

Set `mode` to `rag` for retrieval-grounded generation or `agentic` for the same
retrieval plus a bounded function-calling loop. Agentic mode registers
`search_directory(name)`, `send_email(to, body)`, and
`delete_employee_record(id)`. These are logged canned demo stubs: they do not
access a directory, send email, or delete records. Email and deletion calls are
gated on explicit confirmation.

Set `hardened: true` to activate the prompt-injection input filter and remove
retrieved sentences that appear to override instructions or request hidden
prompt/canary disclosure. It deliberately preserves ordinary imperative HR policy
clauses. This heuristic hardening is a prototype safeguard, not a security
boundary. The canary is redacted from all response strings before returning them.

## Run the Streamlit assistant

```powershell
uv run streamlit run src/sentinel_project/ui/streamlit_app.py
```

Successful requests are stored in the SQLite database configured by
`DATABASE_URL` (by default, `sentinel.db`). The `assistant_interactions` table
stores the prompt, full conversation, response, mode, policy verdict, and
retrieved policy IDs. Keep this database local because it contains user input
and assistant responses.

## Notes

This is still a starter scaffold for the capstone, but the architecture is consistent with a policy-evaluation system and is ready for expanding into retrieval, evaluation, and reporting components.
