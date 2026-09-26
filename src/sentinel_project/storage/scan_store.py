from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ScanRow(Base):
    __tablename__ = "scans"

    scan_id: Mapped[str] = mapped_column(String, primary_key=True)
    budget: Mapped[int] = mapped_column(Integer, nullable=False)
    planner: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttackRow(Base):
    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(String, primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.scan_id"), index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    seed_id: Mapped[str | None] = mapped_column(String)
    parent_attempt_id: Mapped[str | None] = mapped_column(String)
    mutation_depth: Mapped[int] = mapped_column(Integer, default=0)
    strategy_used: Mapped[str] = mapped_column(String, nullable=False)
    conversation_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_breach_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TraceRow(Base):
    __tablename__ = "traces"

    trace_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"), index=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_json: Mapped[str] = mapped_column(Text, nullable=False)
    transport_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class VerdictRow(Base):
    __tablename__ = "verdicts"

    verdict_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"), index=True)
    judge_version: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    policy_violated_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class HumanLabelRow(Base):
    __tablename__ = "human_labels"

    label_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"), index=True)
    labeler_id: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    policy_violated_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_span: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class FindingRow(Base):
    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.scan_id"), index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ScanStore:
    """Persist scan runs and their auditable records to the shared SQLite file."""

    def __init__(self, database_url: str = "sqlite:///./sentinel.db") -> None:
        if not database_url.startswith("sqlite:"):
            raise ValueError("ScanStore currently requires a SQLite database URL")
        self.engine = create_engine(database_url, future=True)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def create_scan(self, budget: int, planner: str, config: dict[str, Any]) -> str:
        scan_id = str(uuid4())
        with self.sessions.begin() as session:
            session.add(ScanRow(
                scan_id=scan_id,
                budget=budget,
                planner=planner,
                status="running",
                config_json=json.dumps(config),
            ))
        return scan_id

    def finish_scan(
        self,
        scan_id: str,
        *,
        status: str,
        estimated_cost_usd: float,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> None:
        with self.sessions.begin() as session:
            row = session.get(ScanRow, scan_id)
            if row:
                row.status = status
                row.estimated_cost_usd = estimated_cost_usd
                row.completed_at = datetime.now(UTC)
                config = json.loads(row.config_json)
                config["cost_breakdown"] = cost_breakdown or {}
                row.config_json = json.dumps(config)

    def save_attempt(self, scan_id: str, attempt: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.merge(AttackRow(
                attempt_id=attempt["id"],
                scan_id=scan_id,
                category=attempt["category"],
                seed_id=attempt.get("seed_id"),
                parent_attempt_id=attempt.get("parent_attempt_id"),
                mutation_depth=attempt.get("mutation_depth", 0),
                strategy_used=attempt["strategy_used"],
                conversation_json=json.dumps(attempt.get("conversation", [])),
                expected_breach_json=json.dumps(attempt.get("expected_breach", [])),
            ))

    def save_trace(self, attempt_id: str, trace: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(TraceRow(
                attempt_id=attempt_id,
                request_json=json.dumps(trace.get("request", {})),
                response_text=str(trace.get("response", "")),
                trace_json=json.dumps(trace, ensure_ascii=True, default=str),
                transport_status=trace.get("status_code"),
                latency_ms=int(trace.get("latency_ms", 0)),
                estimated_cost_usd=float(trace.get("estimated_cost_usd", 0.0)),
            ))

    def save_verdict(self, attempt_id: str, verdict: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(VerdictRow(
                attempt_id=attempt_id,
                judge_version=verdict["judge_version"],
                verdict=verdict["verdict"],
                confidence=verdict["confidence"],
                policy_violated_json=json.dumps(verdict.get("policy_violated", [])),
                evidence_span=verdict.get("evidence_span"),
                severity=verdict.get("severity"),
                reasoning=verdict["reasoning"],
            ))

    def save_label(
        self,
        attempt_id: str,
        labeler_id: str,
        verdict: str,
        *,
        policies: list[str] | None = None,
        evidence_span: str | None = None,
        notes: str = "",
    ) -> str:
        if verdict not in {"breach", "defended", "not_delivered", "ambiguous"}:
            raise ValueError("Invalid human verdict")
        label_id = str(uuid4())
        with self.sessions.begin() as session:
            session.add(HumanLabelRow(
                label_id=label_id,
                attempt_id=attempt_id,
                labeler_id=labeler_id,
                verdict=verdict,
                policy_violated_json=json.dumps(policies or []),
                evidence_span=evidence_span,
                notes=notes,
            ))
        return label_id

    def save_finding(
        self,
        scan_id: str,
        *,
        category: str,
        root_cause: str,
        severity: str,
        summary: str,
        attempt_ids: list[str],
    ) -> str:
        finding_id = str(uuid4())
        with self.sessions.begin() as session:
            session.add(FindingRow(
                finding_id=finding_id,
                scan_id=scan_id,
                category=category,
                root_cause=root_cause,
                severity=severity,
                summary=summary,
                attempt_ids_json=json.dumps(attempt_ids),
            ))
        return finding_id

    def prepare_label_sample(
        self,
        scan_id: str,
        *,
        size: int = 200,
        labeler_ids: list[str],
        calibration_size: int = 50,
        seed: int = 42,
    ) -> list[str]:
        reviewer_ids = list(dict.fromkeys(value.strip() for value in labeler_ids if value.strip()))
        if len(reviewer_ids) != 5:
            raise ValueError("Exactly five distinct reviewer IDs are required")
        if size < calibration_size:
            raise ValueError("Sample size must be at least the calibration size")
        with self.sessions.begin() as session:
            scan = session.get(ScanRow, scan_id)
            if scan is None:
                raise ValueError("Unknown scan ID")
            attempt_ids = list(session.scalars(
                select(AttackRow.attempt_id)
                .where(AttackRow.scan_id == scan_id)
                .order_by(AttackRow.created_at.asc(), AttackRow.attempt_id.asc())
            ).all())
            if len(attempt_ids) < size:
                raise ValueError(f"The scan has {len(attempt_ids)} attempts; {size} are required")
            sample = random.Random(seed).sample(attempt_ids, size)
            config = json.loads(scan.config_json)
            config["label_sample_attempt_ids"] = sample
            config["calibration_size"] = calibration_size
            config["reviewer_ids"] = reviewer_ids
            scan.config_json = json.dumps(config)
            return sample

    def label_queue(
        self,
        scan_id: str | None = None,
        *,
        labeler_id: str | None = None,
        calibration_size: int = 50,
        required_labelers: int = 5,
    ) -> list[dict[str, Any]]:
        with self.sessions() as session:
            stmt = select(AttackRow, TraceRow, VerdictRow).join(TraceRow).outerjoin(VerdictRow)
            if scan_id:
                stmt = stmt.where(AttackRow.scan_id == scan_id)
            stmt = stmt.order_by(AttackRow.created_at.asc(), AttackRow.attempt_id.asc())
            rows = session.execute(stmt).all()
            sample_ids: list[str] | None = None
            reviewer_ids: list[str] = []
            configured_calibration_size = calibration_size
            if scan_id:
                scan = session.get(ScanRow, scan_id)
                if scan:
                    config = json.loads(scan.config_json)
                    sample_ids = config.get("label_sample_attempt_ids")
                    reviewer_ids = config.get("reviewer_ids", [])
                    configured_calibration_size = int(config.get("calibration_size", calibration_size))
                if sample_ids is None:
                    return []
            if sample_ids is not None:
                sample_order = {attempt_id: index for index, attempt_id in enumerate(sample_ids)}
                rows = [row for row in rows if row[0].attempt_id in sample_order]
                rows.sort(key=lambda row: sample_order[row[0].attempt_id])
            all_labels = session.scalars(select(HumanLabelRow)).all()
            labelers_by_attempt: dict[str, set[str]] = {}
            labeled_by: dict[str, set[str]] = {}
            for label in all_labels:
                labelers_by_attempt.setdefault(label.attempt_id, set()).add(label.labeler_id)
                labeled_by.setdefault(label.labeler_id, set()).add(label.attempt_id)

            calibration_rows = rows[:configured_calibration_size]
            reviewer_count = len(reviewer_ids) or required_labelers
            calibration_complete = len(calibration_rows) == configured_calibration_size and all(
                len(labelers_by_attempt.get(attack.attempt_id, set())) >= reviewer_count
                for attack, _, _ in calibration_rows
            )
            if calibration_complete:
                selected_rows = rows[configured_calibration_size:]
            else:
                selected_rows = calibration_rows
            if labeler_id:
                if reviewer_ids and labeler_id not in reviewer_ids:
                    return []
                selected_rows = [
                    row for row in selected_rows
                    if row[0].attempt_id not in labeled_by.get(labeler_id, set())
                ]
                if calibration_complete and reviewer_ids:
                    remainder_start = configured_calibration_size
                    reviewer_index = reviewer_ids.index(labeler_id)
                    selected_rows = [
                        row for row in selected_rows
                        if sample_order[row[0].attempt_id] >= remainder_start
                        and (sample_order[row[0].attempt_id] - remainder_start) % reviewer_count == reviewer_index
                    ]
            calibration_ids = {row[0].attempt_id for row in calibration_rows}
            return [
                {
                    "attempt_id": attack.attempt_id,
                    "scan_id": attack.scan_id,
                    "category": attack.category,
                    "attempt": json.loads(attack.conversation_json),
                    "trace": json.loads(trace.trace_json),
                    "judge_verdict": verdict.verdict if verdict else "",
                    "calibration": attack.attempt_id in calibration_ids,
                }
                for attack, trace, verdict in selected_rows
            ]

    def traces_for_scan(self, scan_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.execute(
                select(AttackRow, TraceRow, VerdictRow)
                .join(TraceRow, TraceRow.attempt_id == AttackRow.attempt_id)
                .outerjoin(VerdictRow, VerdictRow.attempt_id == AttackRow.attempt_id)
                .where(AttackRow.scan_id == scan_id)
                .order_by(AttackRow.created_at.asc(), AttackRow.attempt_id.asc())
            ).all()
            return [
                {
                    "attempt_id": attempt.attempt_id,
                    "category": attempt.category,
                    "attempt": json.loads(attempt.conversation_json),
                    "trace": json.loads(trace.trace_json),
                    "judge_verdict": verdict.verdict if verdict else "",
                }
                for attempt, trace, verdict in rows
            ]

    def calibration_progress(
        self,
        *,
        scan_id: str | None = None,
        calibration_size: int = 50,
        required_labelers: int = 5,
    ) -> dict[str, int | bool]:
        with self.sessions() as session:
            stmt = select(AttackRow)
            scan = session.get(ScanRow, scan_id) if scan_id else None
            sample_ids: list[str] | None = None
            if scan_id:
                stmt = stmt.where(AttackRow.scan_id == scan_id)
                if scan:
                    config = json.loads(scan.config_json)
                    sample_ids = config.get("label_sample_attempt_ids")
                    calibration_size = int(config.get("calibration_size", calibration_size))
                    required_labelers = len(config.get("reviewer_ids", [])) or required_labelers
            stmt = stmt.order_by(AttackRow.created_at.asc(), AttackRow.attempt_id.asc())
            all_attempts = session.scalars(stmt).all()
            if sample_ids is not None:
                attempts_by_id = {attempt.attempt_id: attempt for attempt in all_attempts}
                attempts = [attempts_by_id[value] for value in sample_ids[:calibration_size] if value in attempts_by_id]
            else:
                attempts = all_attempts[:calibration_size]
            labels = session.scalars(select(HumanLabelRow)).all()
            counts: dict[str, set[str]] = {}
            for label in labels:
                counts.setdefault(label.attempt_id, set()).add(label.labeler_id)
            complete = sum(len(counts.get(attempt.attempt_id, set())) >= required_labelers for attempt in attempts)
            return {
                "attempts": len(attempts),
                "completed": complete,
                "ready_for_full_sample": len(attempts) == calibration_size and complete == calibration_size,
                "prepared": sample_ids is not None,
            }

    def labels_for_metrics(self) -> list[dict[str, str]]:
        with self.sessions() as session:
            rows = session.execute(
                select(AttackRow.attempt_id, AttackRow.category, VerdictRow.verdict, HumanLabelRow.verdict, HumanLabelRow.labeler_id)
                .join(VerdictRow, VerdictRow.attempt_id == AttackRow.attempt_id)
                .join(HumanLabelRow, HumanLabelRow.attempt_id == AttackRow.attempt_id)
            ).all()
            return [
                {
                    "attempt_id": attempt_id,
                    "category": category,
                    "judge_verdict": judge_verdict,
                    "human_verdict": human_verdict,
                    "labeler_id": labeler_id,
                }
                for attempt_id, category, judge_verdict, human_verdict, labeler_id in rows
            ]

    def labeled_traces(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            attempts = session.execute(
                select(AttackRow, TraceRow, VerdictRow)
                .join(TraceRow, TraceRow.attempt_id == AttackRow.attempt_id)
                .outerjoin(VerdictRow, VerdictRow.attempt_id == AttackRow.attempt_id)
                .order_by(AttackRow.created_at.asc(), AttackRow.attempt_id.asc())
            ).all()
            labels = session.scalars(select(HumanLabelRow).order_by(HumanLabelRow.created_at.asc())).all()
            labels_by_attempt: dict[str, list[dict[str, str]]] = {}
            for label in labels:
                labels_by_attempt.setdefault(label.attempt_id, []).append(
                    {"labeler_id": label.labeler_id, "verdict": label.verdict}
                )
            return [
                {
                    "attempt": {
                        "id": attack.attempt_id,
                        "category": attack.category,
                        "seed_id": attack.seed_id,
                        "parent_attempt_id": attack.parent_attempt_id,
                        "mutation_depth": attack.mutation_depth,
                        "strategy_used": attack.strategy_used,
                        "conversation": json.loads(attack.conversation_json),
                        "expected_breach": json.loads(attack.expected_breach_json),
                    },
                    "trace": json.loads(trace.trace_json),
                    "judge_verdict": verdict.verdict if verdict else "",
                    "human_labels": labels_by_attempt.get(attack.attempt_id, []),
                }
                for attack, trace, verdict in attempts
                if labels_by_attempt.get(attack.attempt_id)
            ]

    def findings(self, scan_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            stmt = select(FindingRow)
            if scan_id:
                stmt = stmt.where(FindingRow.scan_id == scan_id)
            rows = session.scalars(stmt.order_by(FindingRow.created_at.desc())).all()
            return [
                {
                    "finding_id": row.finding_id,
                    "scan_id": row.scan_id,
                    "category": row.category,
                    "root_cause": row.root_cause,
                    "severity": row.severity,
                    "summary": row.summary,
                    "attempt_ids": json.loads(row.attempt_ids_json),
                }
                for row in rows
            ]

    def scans(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(select(ScanRow).order_by(ScanRow.started_at.desc())).all()
            return [
                {
                    "scan_id": row.scan_id,
                    "budget": row.budget,
                    "planner": row.planner,
                    "status": row.status,
                    "estimated_cost_usd": row.estimated_cost_usd,
                    "config": json.loads(row.config_json),
                    "started_at": row.started_at.isoformat(),
                }
                for row in rows
            ]