import unittest

from timesfm3_weather_gate import (
    CityGateContract,
    GateThresholds,
    LeadEvidence,
    WeatherCurve,
    WeatherGate,
    derive_switch_rule,
    reconcile_enterprises,
)


def curve(temperature: float, wind: float) -> WeatherCurve:
    return WeatherCurve((temperature,) * 24, (wind,) * 24)


class WeatherGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = WeatherGate(
            {
                "A": CityGateContract(
                    GateThresholds(3.0, 2.0),
                    {3: LeadEvidence(5, 4.0, 0.8, True)},
                ),
                "B": CityGateContract(
                    GateThresholds(1.0, 1.0),
                    {3: LeadEvidence(4, 4.0, 1.0, False)},
                ),
            }
        )

    def test_city_and_lead_evidence_controls_switch(self):
        self.assertTrue(self.gate.decide("A", 3, curve(20, 2), curve(24, 2)).triggered)
        self.assertFalse(self.gate.decide("B", 3, curve(20, 2), curve(24, 2)).triggered)

    def test_hard_ratio_guard_falls_back(self):
        decision = self.gate.decide("A", 3, curve(20, 2), curve(24, 2))
        total, source = self.gate.select_city_total(
            decision, baseline_total=100, enterprise_branch_total=150
        )
        self.assertEqual(100, total)
        self.assertEqual("hard-ratio-fallback", source)

    def test_switch_rule_requires_minimum_evidence(self):
        too_small = derive_switch_rule([(10, 5)] * 4)
        enough = derive_switch_rule([(10, 5)] * 4 + [(10, 12)])
        self.assertFalse(too_small.enabled)
        self.assertTrue(enough.enabled)

    def test_city_local_reconciliation(self):
        result = reconcile_enterprises({"x": 3, "y": 1}, 100)
        self.assertAlmostEqual(100, sum(result.values()))
        self.assertAlmostEqual(75, result["x"])


if __name__ == "__main__":
    unittest.main()

