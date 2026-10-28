"""Model-drift detection (Phase 3.2).

Compares the *current* error of a model/baseline against a stored reference
(the error observed when it was last known-good) and flags degradation beyond
configurable thresholds. The retrain *trigger* is data-gated (needs the rebuilt
velocity dataset to mature), but the detection + alerting is independent and
runs against the live backtest harness today.

Metric is MAPE (lower = better), so drift = a relative INCREASE in error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Relative-degradation thresholds (current vs reference MAPE).
WARN_PCT = 0.15   # +15% error → warn
ALERT_PCT = 0.30  # +30% error → alert (retrain candidate)


@dataclass
class DriftResult:
    horizon: str
    current_mape: float
    reference_mape: float
    relative_change: float          # (current - reference) / reference
    severity: str                   # "none" | "warn" | "alert"
    drifted: bool
    message: str = ""


def detect_drift(
    current_mape: float,
    reference_mape: float,
    *,
    horizon: str = "",
    warn_pct: float = WARN_PCT,
    alert_pct: float = ALERT_PCT,
) -> DriftResult:
    """Compare one horizon's current error to its reference."""
    if reference_mape <= 0:
        rel = 0.0
    else:
        rel = (current_mape - reference_mape) / reference_mape

    if rel >= alert_pct:
        severity, drifted = "alert", True
    elif rel >= warn_pct:
        severity, drifted = "warn", True
    else:
        severity, drifted = "none", False

    msg = (
        f"{horizon}: MAPE {reference_mape:.3f} → {current_mape:.3f} "
        f"({rel:+.0%}) [{severity}]"
    )
    return DriftResult(horizon, current_mape, reference_mape, rel, severity, drifted, msg)


def _current_metric(row: dict, metric_key: str) -> Optional[float]:
    """Prefer the model MAPE; fall back to the best baseline MAPE."""
    if metric_key in row and isinstance(row[metric_key], (int, float)):
        return float(row[metric_key])
    baselines = [
        row[k] for k in ("baseline_persist_mape", "baseline_growth_mape")
        if isinstance(row.get(k), (int, float))
    ]
    return min(baselines) if baselines else None


def evaluate_backtest_drift(
    rows: Iterable[dict],
    reference: dict[str, float],
    *,
    metric_key: str = "model_mape",
    warn_pct: float = WARN_PCT,
    alert_pct: float = ALERT_PCT,
) -> list[DriftResult]:
    """Apply :func:`detect_drift` per horizon. ``rows`` are backtest rows;
    ``reference`` maps ``horizon -> reference MAPE``. Horizons absent from the
    reference are skipped (nothing to compare against yet)."""
    out: list[DriftResult] = []
    for row in rows:
        horizon = row.get("horizon", "")
        ref = reference.get(horizon)
        cur = _current_metric(row, metric_key)
        if ref is None or cur is None:
            continue
        out.append(detect_drift(cur, ref, horizon=horizon,
                                warn_pct=warn_pct, alert_pct=alert_pct))
    return out


@dataclass
class DriftReport:
    results: list[DriftResult] = field(default_factory=list)

    @property
    def alerts(self) -> list[DriftResult]:
        return [r for r in self.results if r.severity == "alert"]

    @property
    def warnings(self) -> list[DriftResult]:
        return [r for r in self.results if r.severity == "warn"]

    @property
    def drifted(self) -> bool:
        return any(r.drifted for r in self.results)

    def summary(self) -> dict[str, Any]:
        return {
            "drifted": self.drifted,
            "n_alerts": len(self.alerts),
            "n_warnings": len(self.warnings),
            "horizons_checked": len(self.results),
            "details": [r.message for r in self.results if r.drifted],
        }
