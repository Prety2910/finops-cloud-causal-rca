"""Local, durable approval ledger for dry-run optimization actions.

This module has no cloud SDK and cannot change infrastructure. It records
plans, checks approver identity against a configured allowlist, simulates a
dry-run transition, and records simulated verification outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


ACTION_KINDS = {"schedule_stop", "resize_vm", "update_scaling_policy"}
SECRET_KEY_PARTS = ("password", "secret", "token", "credential", "api_key", "access_key")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(part in normalized for part in SECRET_KEY_PARTS) or _contains_secret_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


class ActionWorkflow:
    """SQLite-backed action state machine with explicit approval and audit."""

    def __init__(self, db_path: str | Path, authorized_approvers: set[str] | None = None):
        self.db_path = str(db_path)
        self.authorized_approvers = {str(x) for x in (authorized_approvers or set())}
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS action_plans (
                    action_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    action_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approver_id TEXT,
                    outcome_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    actor_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES action_plans(action_id)
                );
            """)

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _audit(self, conn, action_id: str, event: str, actor_id: str | None, details: dict) -> None:
        conn.execute(
            "INSERT INTO action_audit(action_id,event,actor_id,details_json,created_at) VALUES(?,?,?,?,?)",
            (action_id, event, actor_id, self._canonical(details), _utc_now()),
        )

    def plan(
        self,
        *,
        idempotency_key: str,
        recommendation_id: str,
        resource_id: str,
        alert_type: str,
        action_kind: str,
        payload: dict,
    ) -> dict:
        """Create or return an identical pending plan; never execute it."""
        if not all((idempotency_key, recommendation_id, resource_id, alert_type)):
            raise ValueError("idempotency_key, recommendation_id, resource_id, and alert_type are required")
        if action_kind not in ACTION_KINDS:
            raise ValueError(f"action_kind must be one of {sorted(ACTION_KINDS)}")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("action payload must be a non-empty structured object")
        if _contains_secret_key(payload):
            raise ValueError("credentials and secret fields cannot be recorded in an action plan")
        canonical = self._canonical(payload)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        action_id = hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM action_plans WHERE idempotency_key=?",
                                    (idempotency_key,)).fetchone()
            if existing:
                if existing["payload_hash"] != digest or any(
                    existing[key] != val for key, val in {
                        "recommendation_id": recommendation_id, "resource_id": resource_id,
                        "alert_type": alert_type, "action_kind": action_kind,
                    }.items()
                ):
                    raise ValueError("idempotency key already belongs to a different action plan")
                return self.get(action_id)
            conn.execute("""INSERT INTO action_plans
                (action_id,idempotency_key,recommendation_id,resource_id,alert_type,action_kind,
                 payload_json,payload_hash,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (action_id, idempotency_key, recommendation_id, resource_id, alert_type,
                 action_kind, canonical, digest, "planned", now, now))
            self._audit(conn, action_id, "planned", None,
                        {"alert_type": alert_type, "action_kind": action_kind})
        return self.get(action_id)

    def approve(self, action_id: str, approver_id: str) -> dict:
        if not approver_id or approver_id not in self.authorized_approvers:
            raise PermissionError("approver is not in the configured allowlist")
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] != "planned":
                raise ValueError(f"cannot approve action in status {row['status']!r}")
            now = _utc_now()
            conn.execute("UPDATE action_plans SET status='approved',approver_id=?,updated_at=? WHERE action_id=?",
                         (approver_id, now, action_id))
            self._audit(conn, action_id, "approved", approver_id, {"approval_required": True})
        return self.get(action_id)

    def reject(self, action_id: str, approver_id: str, reason: str) -> dict:
        if not approver_id or approver_id not in self.authorized_approvers:
            raise PermissionError("approver is not in the configured allowlist")
        if not reason.strip():
            raise ValueError("a rejection reason is required")
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] != "planned":
                raise ValueError(f"cannot reject action in status {row['status']!r}")
            now = _utc_now()
            conn.execute("UPDATE action_plans SET status='rejected',approver_id=?,updated_at=? WHERE action_id=?",
                         (approver_id, now, action_id))
            self._audit(conn, action_id, "rejected", approver_id, {"reason": reason})
        return self.get(action_id)

    def run_dry_run(self, action_id: str) -> dict:
        """Record a no-side-effect simulation after approval; no cloud calls occur."""
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] != "approved":
                raise ValueError("an allowlisted human approval is required before dry-run")
            outcome = {"mode": "dry_run", "executed": False, "side_effects": False,
                       "message": "Plan reviewed locally; no provider adapter was invoked."}
            now = _utc_now()
            conn.execute("UPDATE action_plans SET status='dry_run_complete',outcome_json=?,updated_at=? WHERE action_id=?",
                         (self._canonical(outcome), now, action_id))
            self._audit(conn, action_id, "dry_run_complete", None, outcome)
        return self.get(action_id)

    def record_simulated_verification(self, action_id: str, checks: dict[str, bool]) -> dict:
        """Record simulation checks only; this does not verify a live change."""
        if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()):
            raise ValueError("checks must be a non-empty mapping of names to booleans")
        passed = all(checks.values())
        status = "simulated_verified" if passed else "simulation_failed"
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] != "dry_run_complete":
                raise ValueError("simulated verification requires a completed dry-run")
            outcome = {"verification_kind": "simulation", "checks": checks,
                       "passed": passed, "live_change_verified": False,
                       "rollback_required": not passed}
            now = _utc_now()
            conn.execute("UPDATE action_plans SET status=?,outcome_json=?,updated_at=? WHERE action_id=?",
                         (status, self._canonical(outcome), now, action_id))
            self._audit(conn, action_id, status, None, outcome)
        return self.get(action_id)

    def record_simulated_rollback(self, action_id: str, reason: str) -> dict:
        """Close a failed simulated verification with a no-side-effect rollback record."""
        if not reason.strip():
            raise ValueError("rollback reason is required")
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["status"] != "simulation_failed":
                raise ValueError("simulated rollback requires failed simulated verification")
            outcome = {"rollback_kind": "simulation", "reason": reason,
                       "live_resource_changed": False}
            now = _utc_now()
            conn.execute("UPDATE action_plans SET status='simulated_rolled_back',outcome_json=?,updated_at=? WHERE action_id=?",
                         (self._canonical(outcome), now, action_id))
            self._audit(conn, action_id, "simulated_rolled_back", None, outcome)
        return self.get(action_id)

    def get(self, action_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM action_plans WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            result["outcome"] = json.loads(result.pop("outcome_json")) if result["outcome_json"] else None
            result.pop("payload_hash")
            result["audit"] = [dict(item) | {"details": json.loads(item["details_json"])}
                               for item in conn.execute(
                                   "SELECT * FROM action_audit WHERE action_id=? ORDER BY audit_id",
                                   (action_id,)).fetchall()]
            for item in result["audit"]:
                item.pop("details_json")
            return result
