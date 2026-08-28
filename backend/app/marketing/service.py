from __future__ import annotations

import logging
import uuid
from typing import Any

from ..workers.credentials import (
    CredentialError,
    get_credential_secret,
    revoke_credential,
    store_credential,
)
from ..integrations.amazon_ads.client import AmazonAdsClient, AmazonAdsError, TokenExpiredError
from ..integrations.amazon_ads.mock_client import MockAmazonAdsClient
from .audit import record_action_audit
from .evaluation import evaluate_action
from .ingestion import ingest_all_profiles, ingest_profile
from .metrics import compare_windows
from .optimizer import optimize_profile, rank_winners_and_waste
from .policy import PolicyViolation, can_execute_write, get_break_even_config, get_write_authority, validate_proposed_change
from .schema import ActionStatus, EntityType, RecommendationAction
from .store import (
    AMAZON_ADS_ENV,
    get_connection,
    list_connections,
    list_recommendations,
    load_campaign_data,
    load_policy,
    revoke_connection,
    save_connection,
    save_policy,
    update_recommendation_status,
)

logger = logging.getLogger(__name__)

OAUTH_CAPABILITY = "amazon_ads.oauth"


class MarketingService:
    def __init__(self, client: AmazonAdsClient | None = None) -> None:
        self._client = client or MockAmazonAdsClient()

    @property
    def client(self) -> AmazonAdsClient:
        return self._client

    # --- OAuth ---

    def start_oauth(self, *, label: str, profile_ids: list[str], redirect_uri: str) -> dict[str, Any]:
        state = str(uuid.uuid4())
        auth_url = self._client.build_authorization_url(state=state, redirect_uri=redirect_uri)
        connection = save_connection(
            {
                "id": str(uuid.uuid4()),
                "label": label,
                "profile_ids": profile_ids,
                "redirect_uri": redirect_uri,
                "oauth_state": state,
                "status": "pending",
            }
        )
        return {"connection_id": connection["id"], "authorization_url": auth_url, "state": state}

    def complete_oauth(self, *, connection_id: str, code: str, state: str) -> dict[str, Any]:
        conn = get_connection(connection_id)
        if conn is None:
            raise ValueError("connection not found")
        if conn.get("oauth_state") != state:
            raise ValueError("invalid oauth state")
        tokens = self._client.exchange_code(code=code, redirect_uri=str(conn.get("redirect_uri") or ""))
        access = str(tokens.get("access_token") or "")
        refresh = str(tokens.get("refresh_token") or "")
        if not access:
            raise ValueError("no access token returned")

        cred = store_credential(
            AMAZON_ADS_ENV,
            capability=OAUTH_CAPABILITY,
            label=f"amazon-ads:{connection_id}",
            secret=refresh or access,
            credential_id=connection_id,
        )
        updated = save_connection(
            {
                **conn,
                "status": "connected",
                "credential_id": cred["id"],
                "access_token": access,
                "refresh_token": refresh,
                "token_expires_at": tokens.get("expires_at"),
            }
        )
        safe = {k: v for k, v in updated.items() if k not in {"access_token", "refresh_token"}}
        return safe

    def refresh_oauth(self, connection_id: str) -> dict[str, Any]:
        conn = get_connection(connection_id)
        if conn is None:
            raise ValueError("connection not found")
        refresh = conn.get("refresh_token") or get_credential_secret(AMAZON_ADS_ENV, connection_id)
        if not refresh:
            raise ValueError("no refresh token available")
        try:
            tokens = self._client.refresh_token(refresh_token=str(refresh))
        except TokenExpiredError as exc:
            raise ValueError("token refresh failed — re-authorize required") from exc
        access = str(tokens.get("access_token") or "")
        if not access:
            raise ValueError("refresh returned no access token")
        updated = save_connection({**conn, "access_token": access, "token_expires_at": tokens.get("expires_at")})
        return {k: v for k, v in updated.items() if k not in {"access_token", "refresh_token"}}

    def revoke_oauth(self, connection_id: str) -> dict[str, Any]:
        conn = revoke_connection(connection_id)
        if conn is None:
            raise ValueError("connection not found")
        try:
            revoke_credential(AMAZON_ADS_ENV, connection_id)
        except CredentialError:
            pass
        try:
            self._client.revoke_token(connection_id=connection_id)
        except AmazonAdsError:
            logger.warning("remote revoke failed for %s", connection_id)
        return conn

    def list_connections(self) -> list[dict[str, Any]]:
        return list_connections()

    # --- Ingestion & analytics ---

    def ingest(self, *, profile_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        return ingest_profile(self._client, profile_id=profile_id, start_date=start_date, end_date=end_date)

    def ingest_scheduled(self, *, start_date: str, end_date: str) -> dict[str, Any]:
        return ingest_all_profiles(self._client, start_date=start_date, end_date=end_date)

    def health(self, profile_id: str) -> dict[str, Any]:
        data = load_campaign_data(profile_id)
        policy = load_policy()
        be = get_break_even_config()
        return {
            "profile_id": profile_id,
            "has_data": bool(data),
            "updated_at": data.get("updated_at"),
            "write_authority": get_write_authority().value,
            "break_even_roas": policy.get("break_even"),
            "connections": len(list_connections()),
        }

    def metrics(self, profile_id: str, *, end_date: str) -> dict[str, Any]:
        from .schema import PerformanceSnapshot

        data = load_campaign_data(profile_id)
        all_snapshots: list[PerformanceSnapshot] = []
        for kw in data.get("keywords") or []:
            for m in kw.get("metrics") or []:
                if not isinstance(m, dict):
                    continue
                all_snapshots.append(
                    PerformanceSnapshot(
                        date=str(m.get("date") or ""),
                        spend=float(m.get("spend") or 0),
                        sales=float(m.get("sales") or 0),
                        orders=int(m.get("orders") or 0),
                        clicks=int(m.get("clicks") or 0),
                        impressions=int(m.get("impressions") or 0),
                        ctr=m.get("ctr"),
                        cpc=m.get("cpc"),
                        conversion_rate=m.get("conversion_rate"),
                        acos=m.get("acos"),
                        roas=m.get("roas"),
                    )
                )
        return {
            "profile_id": profile_id,
            "windows": compare_windows(all_snapshots, end_date=end_date),
        }

    def recommendations(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        return [r.as_dict() for r in list_recommendations(profile_id=profile_id)]

    def pending_approvals(self) -> list[dict[str, Any]]:
        pending = list_recommendations(status=ActionStatus.SUGGESTED)
        pending += list_recommendations(status=ActionStatus.PENDING_APPROVAL)
        return [r.as_dict() for r in pending]

    def winners_waste(self, profile_id: str, *, end_date: str, days: int = 30) -> dict[str, Any]:
        return rank_winners_and_waste(profile_id, end_date=end_date, days=days)

    # --- Policy ---

    def get_policy(self) -> dict[str, Any]:
        return load_policy()

    def update_policy(self, updates: dict[str, Any]) -> dict[str, Any]:
        return save_policy(updates)

    # --- Actions ---

    def approve_recommendation(self, rec_id: str, *, actor: str) -> dict[str, Any]:
        rec = update_recommendation_status(rec_id, ActionStatus.APPROVED)
        if rec is None:
            raise ValueError("recommendation not found")
        return rec.as_dict()

    def execute_recommendation(
        self,
        rec_id: str,
        *,
        actor: str,
        approved: bool = False,
        approval_source: str = "manual",
    ) -> dict[str, Any]:
        recs = list_recommendations()
        rec = next((r for r in recs if r.id == rec_id), None)
        if rec is None:
            raise ValueError("recommendation not found")

        allowed, reason = can_execute_write(approved=approved or rec.status == ActionStatus.APPROVED)
        if not allowed:
            update_recommendation_status(rec_id, ActionStatus.PENDING_APPROVAL)
            return {"executed": False, "reason": reason, "recommendation_id": rec_id}

        before = self._entity_state(rec.profile_id, rec.entity_type, rec.entity_id)
        after = self._apply_change(before, rec.proposed_action, rec.proposed_change)

        try:
            validate_proposed_change(
                entity_id=rec.entity_id,
                action=rec.proposed_action.value,
                before=before,
                after=after,
                evidence_days=rec.evidence_window_days,
                projected_daily_spend=after.get("projected_daily_spend"),
            )
        except PolicyViolation as exc:
            update_recommendation_status(rec_id, ActionStatus.REJECTED)
            return {"executed": False, "reason": str(exc), "recommendation_id": rec_id}

        conn = self._connection_for_profile(rec.profile_id)
        if conn is None:
            return {"executed": False, "reason": "no connection", "recommendation_id": rec_id}

        try:
            api_result = self._client.apply_action(
                profile_id=rec.profile_id,
                entity_type=rec.entity_type.value,
                entity_id=rec.entity_id,
                action=rec.proposed_action.value,
                change=rec.proposed_change,
                access_token=str(conn.get("access_token") or ""),
            )
        except AmazonAdsError as exc:
            update_recommendation_status(rec_id, ActionStatus.FAILED)
            return {"executed": False, "reason": str(exc), "recommendation_id": rec_id}

        audit = record_action_audit(
            recommendation_id=rec_id,
            entity_type=rec.entity_type,
            entity_id=rec.entity_id,
            action=rec.proposed_action,
            before=before,
            after=after,
            actor=actor,
            approval_source=approval_source,
            api_result=api_result,
            rollback_metadata=self._rollback_metadata(before, rec.proposed_action),
        )
        update_recommendation_status(rec_id, ActionStatus.EXECUTED)
        evaluation = evaluate_action(
            profile_id=rec.profile_id,
            recommendation_id=rec_id,
            entity_type=rec.entity_type.value,
            entity_id=rec.entity_id,
        )
        return {
            "executed": True,
            "audit_id": audit.id,
            "api_result": api_result,
            "evaluation": evaluation,
        }

    def _connection_for_profile(self, profile_id: str) -> dict[str, Any] | None:
        for conn in list_connections(include_revoked=False):
            if profile_id in (conn.get("profile_ids") or []):
                return get_connection(str(conn.get("id") or ""))
        return None

    def _entity_state(self, profile_id: str, entity_type: EntityType, entity_id: str) -> dict[str, Any]:
        data = load_campaign_data(profile_id)
        key = {
            EntityType.CAMPAIGN: "campaigns",
            EntityType.AD_GROUP: "ad_groups",
            EntityType.KEYWORD: "keywords",
            EntityType.TARGET: "keywords",
            EntityType.SEARCH_TERM: "search_terms",
            EntityType.PLACEMENT: "placements",
        }[entity_type]
        for row in data.get(key) or []:
            if isinstance(row, dict) and row.get("id") == entity_id:
                return dict(row)
        return {"id": entity_id}

    def _apply_change(
        self,
        before: dict[str, Any],
        action: RecommendationAction,
        change: dict[str, Any],
    ) -> dict[str, Any]:
        after = dict(before)
        if action == RecommendationAction.PAUSE:
            after["status"] = "paused"
        elif action == RecommendationAction.UNPAUSE:
            after["status"] = "enabled"
        elif action in {RecommendationAction.DECREASE_BID, RecommendationAction.INCREASE_BID}:
            bid = float(before.get("bid") or 0)
            pct = float(change.get("bid_change_pct") or 0) / 100
            after["bid"] = round(bid * (1 + pct), 2)
        elif action in {RecommendationAction.DECREASE_BUDGET, RecommendationAction.INCREASE_BUDGET}:
            budget = float(before.get("budget") or 0)
            pct = float(change.get("budget_change_pct") or 0) / 100
            after["budget"] = round(budget * (1 + pct), 2)
        elif action == RecommendationAction.ADD_NEGATIVE:
            after["negative_added"] = change.get("negative")
        return after

    def _rollback_metadata(self, before: dict[str, Any], action: RecommendationAction) -> dict[str, Any]:
        inverse = {
            RecommendationAction.PAUSE: RecommendationAction.UNPAUSE,
            RecommendationAction.UNPAUSE: RecommendationAction.PAUSE,
            RecommendationAction.DECREASE_BID: RecommendationAction.INCREASE_BID,
            RecommendationAction.INCREASE_BID: RecommendationAction.DECREASE_BID,
            RecommendationAction.DECREASE_BUDGET: RecommendationAction.INCREASE_BUDGET,
            RecommendationAction.INCREASE_BUDGET: RecommendationAction.DECREASE_BUDGET,
        }
        return {"inverse_action": inverse.get(action, action).value, "restore": dict(before)}
