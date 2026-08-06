"""Site-local trigger runner for CX Portal execution profiles."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from utils.execution_profiles import ExecutionProfileStore
    from utils.gitlab_pipeline import (
        build_pipeline_plan,
        configured_gitlab_target,
        configured_gitlab_trigger_token,
        submit_pipeline_plan,
    )
except ModuleNotFoundError:  # pragma: no cover - supports python -m result_server.trigger_runner
    from result_server.utils.execution_profiles import ExecutionProfileStore
    from result_server.utils.gitlab_pipeline import (
        build_pipeline_plan,
        configured_gitlab_target,
        configured_gitlab_trigger_token,
        submit_pipeline_plan,
    )


@dataclass(frozen=True)
class TriggerEvaluation:
    """Dry-run or submit evaluation result for one trigger definition."""

    trigger_id: str
    trigger_type: str
    should_fire: bool
    reason: str
    status: str
    payload: dict
    errors: list[str]
    observations: list[dict]


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0)


def _parse_repo_ref_target(target: str) -> tuple[str, str] | None:
    repo, sep, ref = target.strip().rpartition("@")
    if not sep or not repo.strip() or not ref.strip():
        return None
    return repo.strip(), ref.strip()


def _git_ls_remote(repo: str, ref: str, *, timeout: float = 20.0) -> str:
    completed = subprocess.run(
        ["git", "ls-remote", repo, ref],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    first_line = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
    return first_line.split()[0] if first_line.split() else ""


def _cron_field_matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    for part in field.split(","):
        item = part.strip()
        if not item:
            continue
        step = 1
        base = item
        if "/" in item:
            base, step_text = item.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                return False
            if step <= 0:
                return False
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                return False
        else:
            try:
                start = end = int(base)
            except ValueError:
                return False
        if start < minimum or end > maximum or start > end:
            return False
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def cron_matches(cron_expr: str, now: datetime) -> tuple[bool, list[str]]:
    """Return whether a 5-field cron expression matches the given aware datetime."""
    fields = cron_expr.split()
    if len(fields) != 5:
        return False, ["cron expression must have 5 fields"]
    minute, hour, day, month, weekday = fields
    checks = [
        (minute, now.minute, 0, 59),
        (hour, now.hour, 0, 23),
        (day, now.day, 1, 31),
        (month, now.month, 1, 12),
        (weekday, (now.weekday() + 1) % 7, 0, 6),
    ]
    return all(
        _cron_field_matches(field, value, minimum, maximum)
        for field, value, minimum, maximum in checks
    ), []


def _trigger_now(trigger: dict, now: datetime) -> tuple[datetime, list[str]]:
    timezone_name = trigger.get("timezone") or "Asia/Tokyo"
    try:
        return now.astimezone(ZoneInfo(timezone_name)), []
    except ZoneInfoNotFoundError:
        return now, [f"unknown timezone: {timezone_name}"]


def _profile_scope_csv(profile: dict | None, key: str) -> str:
    if not profile:
        return ""
    return ",".join(str(value).strip() for value in profile.get(key, []) if str(value).strip())


def _build_trigger_plan(
    store: ExecutionProfileStore,
    trigger: dict,
    *,
    result_server_url: str,
    trigger_reason: str,
) -> tuple[dict, list[str]]:
    profile_result = store.resolve_profile(profile_id=trigger.get("profile_id", ""))
    profile = profile_result.profile
    gitlab_target, target_errors = configured_gitlab_target(trigger.get("gitlab_target", ""))
    target_ref = trigger.get("target_ref") or os.environ.get("RESULT_SERVER_GITLAB_REF", "develop")
    code = _profile_scope_csv(profile, "code")
    system = _profile_scope_csv(profile, "system")
    plan = build_pipeline_plan(
        gitlab_repo=gitlab_target.repo if gitlab_target else "",
        target_ref=target_ref,
        code=code,
        system=system,
        allocation_project_id=profile_result.allocation_project_id,
        scheduler_extra_args="",
        result_server_url=result_server_url,
        target_id=gitlab_target.id if gitlab_target else trigger.get("gitlab_target", ""),
    )
    variables = dict(plan.payload.get("variables", {}))
    variables["BK_TRIGGER_ID"] = trigger.get("id", "")
    variables["BK_TRIGGER_TYPE"] = trigger.get("trigger_type", "")
    variables["BK_TRIGGER_REASON"] = trigger_reason
    plan_payload = {"ref": plan.payload.get("ref", target_ref), "variables": variables}
    payload = {
        "api_url": plan.api_url,
        "gitlab_target": gitlab_target.id if gitlab_target else trigger.get("gitlab_target", ""),
        "gitlab_project": gitlab_target.repo if gitlab_target else "",
        "payload": plan_payload,
    }
    errors = list(profile_result.errors) + target_errors + plan.errors
    if profile and not profile_result.allocation_project_id:
        errors.append("profile allocation_project_id is required")
    return payload, errors


def evaluate_scheduled_trigger(
    store: ExecutionProfileStore,
    trigger: dict,
    *,
    now: datetime,
    result_server_url: str,
) -> TriggerEvaluation:
    local_now, timezone_errors = _trigger_now(trigger, now)
    matches, cron_errors = cron_matches(trigger.get("cron_expr", ""), local_now)
    reason = f"cron:{trigger.get('cron_expr', '')}"
    payload, plan_errors = _build_trigger_plan(
        store,
        trigger,
        result_server_url=result_server_url,
        trigger_reason=reason,
    )
    errors = timezone_errors + cron_errors + plan_errors
    should_fire = matches and not errors
    status = "would_submit" if should_fire else "not_due"
    if errors:
        status = "blocked"
    return TriggerEvaluation(
        trigger_id=trigger["id"],
        trigger_type=trigger["trigger_type"],
        should_fire=should_fire,
        reason=reason,
        status=status,
        payload=payload,
        errors=errors,
        observations=[],
    )


def evaluate_repo_ref_trigger(
    store: ExecutionProfileStore,
    trigger: dict,
    *,
    now: datetime,
    result_server_url: str,
    ls_remote=_git_ls_remote,
) -> TriggerEvaluation:
    observations = []
    errors: list[str] = []
    changed_targets = []
    initialized_targets = []
    for target in trigger.get("watch_targets", []):
        parsed = _parse_repo_ref_target(target)
        if parsed is None:
            errors.append(f"invalid repo_ref target: {target}")
            continue
        repo, ref = parsed
        try:
            fingerprint = ls_remote(repo, ref)
        except (subprocess.SubprocessError, OSError) as exc:
            errors.append(f"failed to observe {target}: {exc}")
            continue
        if not fingerprint:
            errors.append(f"empty fingerprint for {target}")
            continue
        previous = store.get_trigger_observation(trigger["id"], target)
        initialized = previous is None
        changed = not initialized and previous.get("fingerprint") != fingerprint
        if initialized:
            initialized_targets.append(target)
        if changed:
            changed_targets.append(target)
        observations.append(
            {
                "target": target,
                "fingerprint": fingerprint,
                "previous_fingerprint": previous.get("fingerprint") if previous else "",
                "initialized": initialized,
                "changed": changed,
            }
        )

    match_mode = trigger.get("match_mode") or "any"
    if match_mode == "all":
        should_fire = bool(observations) and all(item["changed"] for item in observations)
    else:
        should_fire = any(item["changed"] for item in observations)
    reason_targets = changed_targets or initialized_targets
    reason = "repo_ref:" + ",".join(reason_targets)
    payload, plan_errors = _build_trigger_plan(
        store,
        trigger,
        result_server_url=result_server_url,
        trigger_reason=reason,
    )
    errors.extend(plan_errors)
    status = "would_submit" if should_fire and not errors else "unchanged"
    if initialized_targets and not should_fire and not errors:
        status = "would_initialize"
    if errors:
        status = "blocked"
    return TriggerEvaluation(
        trigger_id=trigger["id"],
        trigger_type=trigger["trigger_type"],
        should_fire=should_fire and not errors,
        reason=reason,
        status=status,
        payload=payload,
        errors=errors,
        observations=observations,
    )


def evaluate_trigger(
    store: ExecutionProfileStore,
    trigger: dict,
    *,
    now: datetime,
    result_server_url: str,
    ls_remote=_git_ls_remote,
) -> TriggerEvaluation:
    if trigger.get("trigger_type") == "scheduled":
        return evaluate_scheduled_trigger(
            store,
            trigger,
            now=now,
            result_server_url=result_server_url,
        )
    if trigger.get("trigger_type") == "watch_event" and trigger.get("watch_kind") == "repo_ref":
        return evaluate_repo_ref_trigger(
            store,
            trigger,
            now=now,
            result_server_url=result_server_url,
            ls_remote=ls_remote,
        )
    return TriggerEvaluation(
        trigger_id=trigger.get("id", ""),
        trigger_type=trigger.get("trigger_type", ""),
        should_fire=False,
        reason="unsupported",
        status="blocked",
        payload={},
        errors=[f"unsupported trigger: {trigger.get('trigger_type')}/{trigger.get('watch_kind')}"],
        observations=[],
    )


def run_triggers(
    *,
    db_path: str,
    dry_run: bool = True,
    result_server_url: str = "",
    now: datetime | None = None,
    record_observations: bool = False,
    submit: bool = False,
    ls_remote=_git_ls_remote,
    submit_pipeline=submit_pipeline_plan,
    use_lock: bool = True,
    lock_name: str = "default",
    lock_ttl_seconds: int = 300,
) -> list[TriggerEvaluation]:
    store = ExecutionProfileStore(db_path)
    current_time = now or _now_utc()
    result_url = result_server_url or os.environ.get("RESULT_SERVER_PUBLIC_URL", "").rstrip("/")
    owner = f"{socket.gethostname()}:{os.getpid()}"
    if use_lock:
        locked = store.acquire_trigger_runner_lock(
            lock_name,
            owner=owner,
            ttl_seconds=lock_ttl_seconds,
            now=current_time.isoformat().replace("+00:00", "Z"),
        )
        if not locked:
            evaluation = TriggerEvaluation(
                trigger_id="__runner__",
                trigger_type="runner",
                should_fire=False,
                reason=f"lock:{lock_name}",
                status="runner_locked",
                payload={"lock_name": lock_name},
                errors=[],
                observations=[],
            )
            store.create_trigger_run(
                trigger_id=evaluation.trigger_id,
                trigger_type=evaluation.trigger_type,
                status=evaluation.status,
                dry_run=dry_run,
                reason=evaluation.reason,
                payload=evaluation.payload,
                errors=[],
                actor="trigger_runner",
            )
            return [evaluation]
    evaluations = []
    try:
        for trigger in store.list_trigger_definitions():
            if not trigger.get("enabled", True):
                continue
            evaluation = evaluate_trigger(
                store,
                trigger,
                now=current_time,
                result_server_url=result_url,
                ls_remote=ls_remote,
            )
            if record_observations:
                observed_at = current_time.isoformat().replace("+00:00", "Z")
                for item in evaluation.observations:
                    store.upsert_trigger_observation(
                        evaluation.trigger_id,
                        item["target"],
                        item["fingerprint"],
                        observed_at=observed_at,
                    )
            status = evaluation.status
            errors = list(evaluation.errors)
            if submit and evaluation.should_fire:
                plan_payload = evaluation.payload.get("payload", {})
                plan = SimpleNamespace(
                    api_url=evaluation.payload.get("api_url", ""),
                    payload=plan_payload,
                    errors=[],
                    target_id=evaluation.payload.get("gitlab_target", ""),
                )
                gitlab_target, _target_errors = configured_gitlab_target(
                    evaluation.payload.get("gitlab_target", "")
                )
                result = submit_pipeline(
                    plan,
                    token=configured_gitlab_trigger_token(gitlab_target),
                )
                errors.extend(result.errors)
                status = "submitted" if result.ok else "submit_failed"
            reported = replace(evaluation, status=status, errors=errors)
            evaluations.append(reported)
            store.create_trigger_run(
                trigger_id=evaluation.trigger_id,
                trigger_type=evaluation.trigger_type,
                status=status,
                dry_run=dry_run,
                reason=evaluation.reason,
                payload=evaluation.payload,
                errors=errors,
                actor="trigger_runner",
            )
    finally:
        if use_lock:
            store.release_trigger_runner_lock(
                lock_name,
                owner=owner,
                now=current_time.isoformat().replace("+00:00", "Z"),
            )
    return evaluations


def _evaluation_to_dict(evaluation: TriggerEvaluation) -> dict:
    return {
        "trigger_id": evaluation.trigger_id,
        "trigger_type": evaluation.trigger_type,
        "should_fire": evaluation.should_fire,
        "reason": evaluation.reason,
        "status": evaluation.status,
        "payload": evaluation.payload,
        "errors": evaluation.errors,
        "observations": evaluation.observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run CX Portal trigger definitions.")
    parser.add_argument("--db", required=True, help="Path to cx_portal.sqlite3")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without submitting GitLab pipelines")
    parser.add_argument("--submit", action="store_true", help="Submit due/changed triggers")
    parser.add_argument(
        "--record-observations",
        action="store_true",
        help="Persist observed repo_ref fingerprints",
    )
    parser.add_argument("--no-lock", action="store_true", help="Do not use the SQLite runner lock")
    parser.add_argument(
        "--lock-ttl-seconds",
        type=int,
        default=300,
        help="SQLite runner lock TTL. Default: 300.",
    )
    parser.add_argument("--result-server-url", default="", help="RESULT_SERVER URL for submitted pipelines")
    args = parser.parse_args(argv)

    if args.submit and args.dry_run:
        parser.error("--submit and --dry-run are mutually exclusive")

    evaluations = run_triggers(
        db_path=args.db,
        dry_run=not args.submit,
        result_server_url=args.result_server_url,
        record_observations=args.record_observations,
        submit=args.submit,
        use_lock=not args.no_lock,
        lock_ttl_seconds=args.lock_ttl_seconds,
    )
    print(json.dumps([_evaluation_to_dict(item) for item in evaluations], indent=2, sort_keys=True))
    return 1 if any(item.errors for item in evaluations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
