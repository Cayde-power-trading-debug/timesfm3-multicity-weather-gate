"""Reference implementation of a city-isolated weather gate.

The gate sits after a model such as TimesFM 3.0.  It does not download, wrap,
or redistribute model weights.  All decisions are made per city and per lead
time so weather from one city cannot directly modify another city's forecast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import fsum
from statistics import fmean
from typing import Iterable, Mapping, Sequence


def _finite(values: Iterable[float]) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result:
        raise ValueError("weather curves must contain at least one value")
    if any(value != value or value in (float("inf"), float("-inf")) for value in result):
        raise ValueError("weather curves must be finite")
    return result


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile from an empty sample")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


@dataclass(frozen=True)
class WeatherCurve:
    """Aligned hourly weather values visible at forecast issue time."""

    temperature_c: tuple[float, ...]
    wind_ms: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "temperature_c", _finite(self.temperature_c))
        object.__setattr__(self, "wind_ms", _finite(self.wind_ms))
        if len(self.temperature_c) != len(self.wind_ms):
            raise ValueError("temperature and wind curves must have equal length")


@dataclass(frozen=True)
class GateThresholds:
    temperature_mean_abs_c: float
    wind_mean_abs_ms: float
    temperature_daily_mean_delta_c: float | None = None
    hot_level_c: float | None = None
    cold_level_c: float | None = None
    level_hours: int = 6
    change_hours: int = 6


@dataclass(frozen=True)
class LeadEvidence:
    """Leakage-safe development evidence for one city and one lead."""

    development_dates: int
    development_gain: float
    development_positive_rate: float
    enabled: bool
    final_dates: int = 0
    final_gain: float | None = None


@dataclass(frozen=True)
class CityGateContract:
    thresholds: GateThresholds
    leads: Mapping[int, LeadEvidence] = field(default_factory=dict)
    hard_ratio_bounds: tuple[float, float] = (0.75, 1.25)
    snapshot_id: str = ""


@dataclass(frozen=True)
class GateDecision:
    city: str
    lead: int
    raw_triggered: bool
    switch_enabled: bool
    triggered: bool
    temperature_hit: bool
    wind_hit: bool
    temperature_mean_abs_c: float
    wind_mean_abs_ms: float
    reason: str


def derive_thresholds(
    historical_curve_pairs: Sequence[tuple[WeatherCurve, WeatherCurve]],
    *,
    quantile: float = 0.80,
) -> GateThresholds:
    """Freeze city-specific thresholds from issue-time-safe historical pairs.

    Each pair is ``(reference_curve, target_forecast_curve)`` as they were both
    visible at the historical issue time.  Use a separate call for every city
    and never carry the returned thresholds across snapshots without review.
    """

    temperature_changes: list[float] = []
    wind_changes: list[float] = []
    daily_temperature_changes: list[float] = []
    hot_levels: list[float] = []
    cold_levels: list[float] = []
    for reference, target in historical_curve_pairs:
        _check_alignment(reference, target)
        temperature_changes.append(_mean_abs_delta(reference.temperature_c, target.temperature_c))
        wind_changes.append(_mean_abs_delta(reference.wind_ms, target.wind_ms))
        daily_temperature_changes.append(abs(fmean(target.temperature_c) - fmean(reference.temperature_c)))
        hot_levels.append(max(target.temperature_c))
        cold_levels.append(min(target.temperature_c))
    return GateThresholds(
        temperature_mean_abs_c=_quantile(temperature_changes, quantile),
        wind_mean_abs_ms=_quantile(wind_changes, quantile),
        temperature_daily_mean_delta_c=_quantile(daily_temperature_changes, quantile),
        hot_level_c=_quantile(hot_levels, quantile),
        cold_level_c=_quantile(cold_levels, 1.0 - quantile),
    )


def derive_switch_rule(
    daily_error_pairs: Sequence[tuple[float, float]],
    *,
    minimum_dates: int = 5,
    minimum_positive_rate: float = 0.60,
) -> LeadEvidence:
    """Learn whether a city/lead may switch, using development dates only.

    Every item is ``(baseline_absolute_error, enterprise_branch_absolute_error)``.
    Positive gain means the weather-aware enterprise branch performed better.
    Independent final-test evidence must be attached later and must not be used
    to reverse-select the switch.
    """

    gains = [float(base) - float(branch) for base, branch in daily_error_pairs]
    positive_rate = sum(gain > 0.0 for gain in gains) / len(gains) if gains else 0.0
    total_gain = fsum(gains)
    enabled = (
        len(gains) >= minimum_dates
        and total_gain > 0.0
        and positive_rate >= minimum_positive_rate
    )
    return LeadEvidence(
        development_dates=len(gains),
        development_gain=total_gain,
        development_positive_rate=positive_rate,
        enabled=enabled,
    )


class WeatherGate:
    """Evaluate gates and select city totals without cross-city propagation."""

    def __init__(self, contracts: Mapping[str, CityGateContract]):
        self.contracts = dict(contracts)

    def decide(
        self,
        city: str,
        lead: int,
        reference: WeatherCurve,
        target_forecast: WeatherCurve,
    ) -> GateDecision:
        contract = self.contracts[city]
        _check_alignment(reference, target_forecast)
        thresholds = contract.thresholds
        temperature_change = _mean_abs_delta(reference.temperature_c, target_forecast.temperature_c)
        wind_change = _mean_abs_delta(reference.wind_ms, target_forecast.wind_ms)
        daily_delta = abs(fmean(target_forecast.temperature_c) - fmean(reference.temperature_c))
        sustained_change = sum(
            abs(right - left) >= thresholds.temperature_mean_abs_c
            for left, right in zip(reference.temperature_c, target_forecast.temperature_c)
        )
        hot_hours = (
            sum(value >= thresholds.hot_level_c for value in target_forecast.temperature_c)
            if thresholds.hot_level_c is not None
            else 0
        )
        cold_hours = (
            sum(value <= thresholds.cold_level_c for value in target_forecast.temperature_c)
            if thresholds.cold_level_c is not None
            else 0
        )
        temperature_hit = temperature_change >= thresholds.temperature_mean_abs_c
        if thresholds.temperature_daily_mean_delta_c is not None:
            temperature_hit = temperature_hit or daily_delta >= thresholds.temperature_daily_mean_delta_c
        temperature_hit = temperature_hit or sustained_change >= thresholds.change_hours
        temperature_hit = temperature_hit or hot_hours >= thresholds.level_hours or cold_hours >= thresholds.level_hours
        wind_hit = wind_change >= thresholds.wind_mean_abs_ms
        raw_triggered = temperature_hit or wind_hit
        evidence = contract.leads.get(int(lead))
        switch_enabled = bool(evidence and evidence.enabled)
        triggered = raw_triggered and switch_enabled
        if triggered:
            reason = "weather threshold reached and city/lead development evidence is positive"
        elif raw_triggered:
            reason = "weather threshold reached, but city/lead switch evidence is insufficient"
        else:
            reason = "temperature and wind changes are below city thresholds"
        return GateDecision(
            city=city,
            lead=int(lead),
            raw_triggered=raw_triggered,
            switch_enabled=switch_enabled,
            triggered=triggered,
            temperature_hit=temperature_hit,
            wind_hit=wind_hit,
            temperature_mean_abs_c=temperature_change,
            wind_mean_abs_ms=wind_change,
            reason=reason,
        )

    def select_city_total(
        self,
        decision: GateDecision,
        *,
        baseline_total: float,
        enterprise_branch_total: float,
    ) -> tuple[float, str]:
        """Choose a city total, applying a hard plausibility fallback."""

        baseline = max(0.0, float(baseline_total))
        branch = max(0.0, float(enterprise_branch_total))
        if not decision.triggered:
            return baseline, "baseline"
        if baseline == 0.0:
            return (branch, "enterprise_branch") if branch == 0.0 else (baseline, "zero-baseline-fallback")
        lower, upper = self.contracts[decision.city].hard_ratio_bounds
        ratio = branch / baseline
        if ratio < lower or ratio > upper:
            return baseline, "hard-ratio-fallback"
        return branch, "enterprise_branch"


def reconcile_enterprises(
    enterprise_predictions: Mapping[str, float],
    city_target: float,
) -> dict[str, float]:
    """Scale non-negative enterprise forecasts to one city target.

    This operation is deliberately city-local.  Call it independently for each
    city; never use a residual from one city to alter enterprises in another.
    """

    clean = {key: max(0.0, float(value)) for key, value in enterprise_predictions.items()}
    total = fsum(clean.values())
    target = max(0.0, float(city_target))
    if not clean:
        return {}
    if total == 0.0:
        equal = target / len(clean)
        return {key: equal for key in clean}
    scale = target / total
    return {key: value * scale for key, value in clean.items()}


def _check_alignment(left: WeatherCurve, right: WeatherCurve) -> None:
    if len(left.temperature_c) != len(right.temperature_c):
        raise ValueError("reference and target curves must be aligned")


def _mean_abs_delta(left: Sequence[float], right: Sequence[float]) -> float:
    return fmean(abs(float(a) - float(b)) for a, b in zip(left, right))

