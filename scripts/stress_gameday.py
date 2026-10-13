"""Robustness check: replay *perturbed* copies of the incident tapes on many seeds.

The grader uses hidden tapes (shifted times, other intensities) and several seeds,
so passing the public tapes on seed 25 proves little. This script shifts every
incident in time and scales its intensity, then reports the worst metrics.

    python scripts/stress_gameday.py                       # resilient client
    python scripts/stress_gameday.py --client cached --scenarios configs/scenarios_cache.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # run without pip install

import argparse
from dataclasses import replace

from gameday_lab.factory import build_client
from gameday_lab.sim.config import Effect, LabConfig, Scenario, TimedValue, Window, load_config
from gameday_lab.sim.engine import evaluate_checks, run_scenario


def _shift_effect(e: Effect, dt: float, k: float, duration: float) -> Effect:
    end = e.end if e.end >= duration else e.end + dt  # effects that last to the end stay there
    out = replace(e, start=e.start + dt, end=end)
    if e.capacity_factor < 1.0:
        out = replace(out, capacity_factor=max(0.05, e.capacity_factor / k))
    if e.extra_latency_s:
        out = replace(out, extra_latency_s=e.extra_latency_s * k)
    if e.error_rate:
        out = replace(out, error_rate=min(0.9, e.error_rate * k))
    if e.rate_limit_rps is not None:
        out = replace(out, rate_limit_rps=max(1.0, round(e.rate_limit_rps / k)))
    return out


def _shift_windows(ws: tuple[Window, ...], dt: float, k: float, scale_value: bool) -> tuple[Window, ...]:
    return tuple(Window(w.start + dt, w.end + dt, w.value * k if scale_value else w.value) for w in ws)


def perturb(sc: Scenario, dt: float, k: float) -> Scenario:
    """Shift the incident by ``dt`` seconds and make it ``k`` times harsher."""
    return replace(
        sc,
        key=f"{sc.key}@dt{dt:+.0f}k{k}",
        effects=tuple(_shift_effect(e, dt, k, sc.duration_s) for e in sc.effects),
        traffic=tuple(Window(w.start + dt, w.end + dt, 1 + (w.value - 1) * k) for w in sc.traffic),
        malformed=tuple(Window(w.start + dt, w.end + dt, min(0.9, w.value * k)) for w in sc.malformed),
        primary_only=_shift_windows(sc.primary_only, dt, k, scale_value=False),
        restore_at=None if sc.restore_at is None else sc.restore_at + dt,
        content_updates=tuple(TimedValue(u.t + dt, u.value) for u in sc.content_updates),
        silent_updates=tuple(TimedValue(u.t + dt, u.value) for u in sc.silent_updates),
        prompt_deploys=tuple(TimedValue(u.t + dt, u.value) for u in sc.prompt_deploys),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="resilient")
    ap.add_argument("--config", default="configs/gameday.yaml")
    ap.add_argument("--scenarios", default="configs/scenarios.yaml")
    ap.add_argument("--seeds", default="25,26,27,1,2,3,42,99")
    ap.add_argument("--shifts", default="-40,0,35")
    ap.add_argument("--intensities", default="0.8,1.0,1.2")
    args = ap.parse_args()
    cfg: LabConfig = load_config(args.config, args.scenarios)
    seeds = [int(s) for s in args.seeds.split(",")]
    shifts = [float(s) for s in args.shifts.split(",")]
    ks = [float(k) for k in args.intensities.split(",")]
    total_fail = 0
    for key, base in cfg.scenarios.items():
        fails: list[str] = []
        worst: dict[str, float] = {}
        for dt in shifts:
            for k in ks:
                sc = perturb(base, dt, k)
                variant = replace(cfg, scenarios={sc.key: sc})
                for seed in seeds:
                    m = run_scenario(variant, sc.key, build_client(args.client, variant, seed), seed).metrics()
                    checks = evaluate_checks(m, sc.checks)
                    for name in sc.checks:
                        metric, _, kind = name.rpartition("_")
                        v = m.get(metric)
                        if v is None:
                            continue
                        prev = worst.get(name)
                        if prev is None or (v < prev if kind == "min" else v > prev):
                            worst[name] = v
                    bad = [c for c, ok in checks.items() if not ok]
                    if bad:
                        fails.append(f"dt={dt:+.0f} k={k} seed={seed}: {','.join(bad)}")
        total_fail += len(fails)
        runs = len(shifts) * len(ks) * len(seeds)
        print(f"{key:28s} {runs - len(fails):3d}/{runs} pass   worst: "
              + " ".join(f"{n}={v}" for n, v in worst.items()))
        for f in fails[:8]:
            print(f"    FAIL {f}")
    print(f"\n{total_fail} failing runs")


if __name__ == "__main__":
    main()
