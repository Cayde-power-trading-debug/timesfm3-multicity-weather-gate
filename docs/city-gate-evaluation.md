# Evaluating a city-specific weather gate without leakage

The reference implementation in this repository separates a regional total baseline from city-level enterprise branches. Its weather gate can switch a **city total** when the city's forecast weather changes and historical evidence supports that switch. This note describes how to evaluate that decision without letting one city's weather or a future observation leak into another city's forecast.

## Freeze what was knowable at issue time

For each rolling forecast origin, retain the weather forecast **vintage** available at that origin. Use that vintage for the target date, and fit thresholds or city/lead enablement rules using earlier origins only. Observed target-day weather is useful for retrospective response analysis, but it is not a substitute for an archived forecast in a production-style backtest.

Split the origins into development and untouched final evaluation periods. Learn trigger thresholds and any city-by-lead benefit switch in development. Freeze them before evaluating the final period. Do not select the best cities, leads, or thresholds from that final score.

## Compare like with like

At every target hour, retain three synthetic or real predictions under the same input cutoff:

1. `B_c(h)`: city baseline allocated from the regional total using historical city load share.
2. `E_c(h)`: city enterprise-branch aggregate with that city's weather covariates.
3. `C_c(h)`: gated choice between `B_c(h)` and `E_c(h)`, including any safety rollback.

Compute each city's error on identical dates and hours. Then sum the chosen city curves and compute a **separate** regional total-curve error. A city-level mean of percentages is not interchangeable with the error of the summed regional curve. Record trigger count, switch count, rollback count, and coverage alongside each metric.

## Preserve city boundaries and conservation

City weights should be proportional to historical load in the same unit, not to historical load divided by the number of enterprises in each city. Otherwise adding enterprises can reduce a city's baseline share without any physical change in load.

When a city switches, reconcile only that city's enterprise detail to `C_c(h)`:

```text
sum(prediction[c, enterprise, h] for enterprise in city_c) == C_c(h)
```

Never spread the residual into another city. Keep the independent regional total branch as an audit anchor, and report any difference between it and the sum of selected city totals.

## Minimal synthetic checks

- Two cities have different enterprise counts but the same total historical load: their baseline shares remain equal.
- A trigger in city A leaves city B's total and enterprise forecasts unchanged.
- No trigger retains the city baseline; an out-of-bound enterprise candidate falls back to that baseline.
- City enterprise sums reconcile to their chosen city totals for every hour.
- Final evaluation scores use a frozen gate policy and only weather vintages available at each forecast origin.

This is a model-agnostic gate. Using TimesFM 3.0 as a branch predictor does not change the weather-vintage or evaluation requirements, and its upstream weights remain subject to their own license.
