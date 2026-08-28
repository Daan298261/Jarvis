# RFC-0015: Amazon Ads integration and bounded optimization

**Status:** accepted  
**Queue item:** Marketing integrations / autonomous campaign optimization  
**Author:** ChatGPT  
**Date:** 2026-08-28

## Problem

Jarvis currently cannot ingest or act on Amazon Ads campaign data. For publishing workflows this prevents automated diagnosis of poor-performing campaigns, keyword waste, budget inefficiency, placement problems, and weak return on ad spend. The user currently reports ROAS of 0.49, which means the system should prioritize loss detection, recommendations, and tightly bounded corrective actions before any broader autonomous spend control.

## Decision

Add an Amazon Ads integration using the official Amazon Ads API and OAuth. Implement the integration in phases, with read-only analytics first and write actions gated by Jarvis capability policy.

The first version SHALL ingest account, campaign, ad group, keyword/target, placement, search-term, spend, sales, orders, clicks, impressions, CTR, CPC, conversion rate, ACOS, and ROAS where available from the API.

Jarvis SHALL normalize Amazon Ads data into a provider-independent marketing model so later integrations can reuse the same optimization and reporting layer.

Jarvis SHALL provide an Amazon Ads optimization agent that can:

- identify high-spend/zero-sale search terms and targets;
- flag keywords/targets whose ACOS or ROAS breaches configured thresholds;
- detect campaigns constrained by budget versus campaigns wasting budget;
- identify candidate negative keywords/targets;
- suggest bid decreases, bid increases, pauses, budget changes, and placement adjustments;
- explain each recommendation using the underlying campaign evidence;
- estimate expected effect where confidence is sufficient;
- track whether an accepted recommendation improved performance after execution.

Write actions SHALL use the normal Jarvis autonomy and approval system. Default behavior is `SUGGEST_ONLY`. Users may later allow `EXECUTE_WITHIN_POLICY` with explicit constraints such as maximum bid change percentage, maximum daily budget change, maximum total daily spend, minimum evidence window, and protected campaigns/keywords that may never be modified automatically.

The Amazon Ads connector SHALL never treat ROAS alone as profit. Optimization logic must support royalty/margin-aware break-even targets so Jarvis can distinguish revenue efficiency from actual contribution margin.

## Acceptance criteria

- [ ] Amazon Ads OAuth connection can be added, refreshed, revoked, and scoped to one or more advertising profiles/accounts.
- [ ] Credentials/tokens are stored through Jarvis' secrets mechanism and are never written to logs or agent memory in plaintext.
- [ ] Scheduled ingestion stores normalized campaign, ad group, target/keyword, placement, search-term, spend, sales, clicks, impressions, orders, CPC, CTR, conversion rate, ACOS, and ROAS metrics where provided.
- [ ] Historical data can be queried by date range and compared across at least 7-day, 14-day, and 30-day windows.
- [ ] Jarvis calculates and displays ROAS and ACOS consistently and supports a configurable break-even ROAS/ACOS derived from user-provided royalty or margin assumptions.
- [ ] Optimization rules detect at minimum: high-spend/no-sale targets, threshold-breaking ACOS/ROAS, low-converting high-click targets, and material CPC changes.
- [ ] Every recommendation records the campaign/entity, evidence window, metrics, rationale, proposed change, estimated impact/confidence, and originating agent.
- [ ] Default Amazon Ads write authority is `SUGGEST_ONLY` and no campaign mutation occurs without an approved capability policy.
- [ ] Write policies support caps for maximum percentage bid change, maximum percentage budget change, absolute daily spend ceiling, protected entities, and minimum sample/evidence thresholds.
- [ ] Approved actions can pause/unpause targets or campaigns, adjust bids, adjust campaign budgets, and add negative keywords/targets where supported by the API.
- [ ] Every write is auditable with before/after values, actor/agent, approval source, timestamp, API result, and rollback metadata when an inverse action is possible.
- [ ] Jarvis performs post-change evaluation and links subsequent performance to the recommendation/action that caused the change.
- [ ] API rate limits, partial failures, token expiration, and unavailable reports fail safely without inventing data or repeating spend-changing writes.
- [ ] UI provides an Amazon Ads dashboard with account health, spend, attributed sales, ROAS, ACOS, trend, top winners, top waste, recommendations, and pending approvals.
- [ ] Automated tests cover metric calculations, threshold logic, permission gates, duplicate-action prevention, OAuth/token handling mocks, and safe failure modes.

## Likely files

| Area | Paths |
| --- | --- |
| Integrations | Amazon Ads OAuth/client/reporting adapter |
| Backend | marketing normalization models, ingestion jobs, optimization service |
| Agents | Amazon Ads / marketing optimization specialist |
| Policy | capability permissions, spend/bid/budget guardrails |
| Scheduler | recurring report ingestion and post-change evaluation |
| Frontend | integrations settings, Amazon Ads dashboard, recommendation/approval views |
| Tests | API mocks, optimizer rules, calculations, policy and audit tests |
| Docs | setup, OAuth, metric semantics, autonomy safety guidance |

## Out of scope

Amazon Seller Central order/inventory management, retail-media channels outside Amazon Ads, automatic creative generation, and unrestricted autonomous budget expansion. These may be separate RFCs.

## Notes

Source/integration target: official Amazon Ads API. Discovery/request date: 2026-08-28. Recommendation: ADAPT STRONGLY for Jarvis marketing automation.

Jarvis should adapt the provider integration into its existing agent, scheduler, approval, audit, and policy architecture rather than build a standalone Amazon-specific automation silo.

Initial operational priority should be diagnosis and recommendation because the reported current ROAS is 0.49. The implementation must optimize against configurable profitability thresholds rather than assume that ROAS above 1.0 is profitable.