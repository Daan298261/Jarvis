from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import BreakEvenConfig, PerformanceSnapshot


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def calculate_roas(sales: float, spend: float) -> float | None:
    return safe_divide(sales, spend)


def calculate_acos(spend: float, sales: float) -> float | None:
    return safe_divide(spend, sales)


def calculate_ctr(clicks: int, impressions: int) -> float | None:
    return safe_divide(float(clicks), float(impressions))


def calculate_cpc(spend: float, clicks: int) -> float | None:
    return safe_divide(spend, float(clicks))


def calculate_conversion_rate(orders: int, clicks: int) -> float | None:
    return safe_divide(float(orders), float(clicks))


def enrich_snapshot(snapshot: PerformanceSnapshot) -> PerformanceSnapshot:
    """Fill derived metrics when base fields are present."""
    if snapshot.ctr is None:
        snapshot.ctr = calculate_ctr(snapshot.clicks, snapshot.impressions)
    if snapshot.cpc is None:
        snapshot.cpc = calculate_cpc(snapshot.spend, snapshot.clicks)
    if snapshot.conversion_rate is None:
        snapshot.conversion_rate = calculate_conversion_rate(snapshot.orders, snapshot.clicks)
    if snapshot.roas is None:
        snapshot.roas = calculate_roas(snapshot.sales, snapshot.spend)
    if snapshot.acos is None:
        snapshot.acos = calculate_acos(snapshot.spend, snapshot.sales)
    return snapshot


def break_even_roas(config: BreakEvenConfig) -> float | None:
    """Contribution-margin-aware break-even ROAS.

    Uses margin_rate when set; otherwise derives from royalty_rate and other costs.
    """
    if config.margin_rate > 0:
        net_margin = config.margin_rate - config.other_costs_pct
    elif config.royalty_rate > 0:
        net_margin = config.royalty_rate - config.other_costs_pct
    else:
        return None
    if net_margin <= 0:
        return None
    return 1.0 / net_margin


def break_even_acos(config: BreakEvenConfig) -> float | None:
    roas = break_even_roas(config)
    if roas is None or roas == 0:
        return None
    return 1.0 / roas


@dataclass
class AggregatedMetrics:
    spend: float = 0.0
    sales: float = 0.0
    orders: int = 0
    clicks: int = 0
    impressions: int = 0
    roas: float | None = None
    acos: float | None = None
    ctr: float | None = None
    cpc: float | None = None
    conversion_rate: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "spend": self.spend,
            "sales": self.sales,
            "orders": self.orders,
            "clicks": self.clicks,
            "impressions": self.impressions,
            "roas": self.roas,
            "acos": self.acos,
            "ctr": self.ctr,
            "cpc": self.cpc,
            "conversion_rate": self.conversion_rate,
        }


def aggregate_snapshots(snapshots: list[PerformanceSnapshot]) -> AggregatedMetrics:
    spend = sum(s.spend for s in snapshots)
    sales = sum(s.sales for s in snapshots)
    orders = sum(s.orders for s in snapshots)
    clicks = sum(s.clicks for s in snapshots)
    impressions = sum(s.impressions for s in snapshots)
    return AggregatedMetrics(
        spend=spend,
        sales=sales,
        orders=orders,
        clicks=clicks,
        impressions=impressions,
        roas=calculate_roas(sales, spend),
        acos=calculate_acos(spend, sales),
        ctr=calculate_ctr(clicks, impressions),
        cpc=calculate_cpc(spend, clicks),
        conversion_rate=calculate_conversion_rate(orders, clicks),
    )


def window_snapshots(
    snapshots: list[PerformanceSnapshot],
    *,
    end_date: str,
    days: int,
) -> list[PerformanceSnapshot]:
    """Select snapshots within a trailing window ending at end_date (inclusive)."""
    if not snapshots:
        return []
    end = end_date
    dates = sorted({s.date for s in snapshots})
    if end not in dates:
        dates.append(end)
        dates.sort()
    try:
        end_idx = dates.index(end)
    except ValueError:
        return []
    start_idx = max(0, end_idx - days + 1)
    window_dates = set(dates[start_idx : end_idx + 1])
    return [s for s in snapshots if s.date in window_dates]


def compare_windows(
    snapshots: list[PerformanceSnapshot],
    *,
    end_date: str,
    windows: tuple[int, ...] = (7, 14, 30),
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for days in windows:
        window = window_snapshots(snapshots, end_date=end_date, days=days)
        out[f"{days}d"] = aggregate_snapshots(window).as_dict()
    return out


def cpc_change_pct(current: AggregatedMetrics, prior: AggregatedMetrics) -> float | None:
    if current.cpc is None or prior.cpc is None or prior.cpc == 0:
        return None
    return (current.cpc - prior.cpc) / prior.cpc
