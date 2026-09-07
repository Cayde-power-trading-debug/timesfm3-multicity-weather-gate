"""Synthetic example; contains no production data or TimesFM weights."""

from timesfm3_weather_gate import (
    CityGateContract,
    GateThresholds,
    LeadEvidence,
    WeatherCurve,
    WeatherGate,
    reconcile_enterprises,
)


def curve(temperature: float, wind: float) -> WeatherCurve:
    return WeatherCurve((temperature,) * 24, (wind,) * 24)


contracts = {
    "City-A": CityGateContract(
        thresholds=GateThresholds(temperature_mean_abs_c=3.0, wind_mean_abs_ms=2.0),
        leads={3: LeadEvidence(7, 12.4, 0.71, enabled=True)},
        snapshot_id="synthetic-v1",
    ),
    "City-B": CityGateContract(
        thresholds=GateThresholds(temperature_mean_abs_c=2.5, wind_mean_abs_ms=1.5),
        leads={3: LeadEvidence(4, 5.0, 0.75, enabled=False)},
        snapshot_id="synthetic-v1",
    ),
}

gate = WeatherGate(contracts)
decision = gate.decide("City-A", 3, curve(20.0, 2.0), curve(24.0, 2.2))
city_total, source = gate.select_city_total(
    decision,
    baseline_total=100.0,
    enterprise_branch_total=108.0,
)
enterprises = reconcile_enterprises({"E-001": 70.0, "E-002": 30.0}, city_total)

print(decision)
print(source, city_total)
print(enterprises)

