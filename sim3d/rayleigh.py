"""
Rayleigh decision-gate for the sealed internal gas.

Purpose: decide whether the internal gas head-space can be treated as a
conducting solid with an effective conductivity (so the cheap conduction-FEM
is valid), or whether natural convection is strong enough to require a true
CFD escalation (OpenFOAM chtMultiRegionFoam).

Physics (horizontal gas layer heated from below, the worst case for onset):
  Ra = g * beta * dT * L^3 / (nu * alpha),   beta = 1/T_film for an ideal gas
  - Ra < 1708              -> no convection, pure conduction, Nu = 1
                             (critical Rayleigh number, verified, see source)
  - Ra >= 1708             -> convection; effective conductivity k_eff = Nu * k
    Nu = 1 + 1.44*[1 - 1708/Ra]+ + [(Ra/5830)^(1/3) - 1]+
    (Hollands et al. 1976; Incropera & DeWitt, Fundamentals of Heat & Mass
    Transfer, eq. 9.49, valid Ra <= 1e8; []+ means clamp-at-zero)
    This is preferred over Globe-Dropkin here because our Ra ~ 1e3-1e4 sits
    below the Globe-Dropkin validity floor (3e5), where it returns Nu < 1.

Engineering rule applied here:
  Nu ~ 1            -> conduction-FEM exact.
  1 < Nu <= ~2      -> conduction-FEM with k_eff = Nu*k is acceptable.
  Nu > ~2 (or Ra outside the correlation band) -> escalate to CFD.

Assumptions flagged [ASSUMED]: gas gap height and the gas-layer temperature
difference are placeholders until the STEP geometry and a first solve fix them.
"""

import math


# Nitrogen properties vs absolute temperature (K), interpolated from standard
# tables (Incropera, Appendix A). Returned: k [W/m.K], nu [m^2/s],
# alpha [m^2/s], Pr [-].
_N2_TABLE = {
    300: dict(k=0.0259, nu=15.86e-6, alpha=22.1e-6, Pr=0.716),
    350: dict(k=0.0293, nu=20.85e-6, alpha=29.6e-6, Pr=0.704),
    400: dict(k=0.0327, nu=26.41e-6, alpha=38.0e-6, Pr=0.695),
}


def gas_properties(t_film_k: float) -> dict:
    """Linear interpolation of N2 properties at the film temperature."""
    temps = sorted(_N2_TABLE)
    t = min(max(t_film_k, temps[0]), temps[-1])
    lo = max(x for x in temps if x <= t)
    hi = min(x for x in temps if x >= t)
    if lo == hi:
        return dict(_N2_TABLE[lo])
    f = (t - lo) / (hi - lo)
    return {key: _N2_TABLE[lo][key] + f * (_N2_TABLE[hi][key] - _N2_TABLE[lo][key])
            for key in _N2_TABLE[lo]}


def rayleigh(dt_k: float, gap_m: float, t_film_k: float, g: float = 9.81) -> tuple:
    """Return (Ra, Pr, props) for a gas layer of height gap_m and surface dT."""
    p = gas_properties(t_film_k)
    beta = 1.0 / t_film_k                       # ideal-gas thermal expansion
    ra = g * beta * dt_k * gap_m**3 / (p["nu"] * p["alpha"])
    return ra, p["Pr"], p


def nusselt(ra: float, pr: float = None) -> float:
    """Hollands enclosure Nusselt number for a layer heated from below.

    Pr is unused (kept for signature stability); the Hollands form is Pr-weak
    for gases. Returns Nu = 1 for Ra < 1708 by construction of the clamps.
    """
    term1 = max(0.0, 1.0 - 1708.0 / ra)
    term2 = max(0.0, (ra / 5830.0) ** (1.0 / 3.0) - 1.0)
    return 1.0 + 1.44 * term1 + term2


def evaluate(dt_k: float, gap_m: float, t_film_k: float) -> dict:
    ra, pr, props = rayleigh(dt_k, gap_m, t_film_k)
    nu = nusselt(ra, pr)
    k_eff = nu * props["k"]
    if nu <= 1.05:
        verdict = "CONDUCTION (Nu=1): conduction-FEM exact"
    elif nu <= 2.0:
        verdict = "EFFECTIVE-K: conduction-FEM with k_eff acceptable"
    else:
        verdict = "ESCALATE: convection strong -> use OpenFOAM CFD"
    band_ok = ra <= 1e8
    return dict(Ra=ra, Pr=pr, Nu=nu, k_gas=props["k"], k_eff=k_eff,
                verdict=verdict, correlation_band_ok=band_ok)


if __name__ == "__main__":
    from config import GEOM

    print("=" * 70)
    print("Rayleigh decision-gate  (sealed internal gas, heated from below)")
    print("=" * 70)
    gap = GEOM.gas_h  # [ASSUMED] 20 mm head-space until STEP fixes it
    print(f"Gas gap height L = {gap*1e3:.1f} mm  [ASSUMED]\n")
    print(f"{'dT [K]':>8} {'T_film[K]':>10} {'Ra':>12} {'Nu':>7} "
          f"{'k_eff[W/mK]':>12}  verdict")
    # Sweep the plausible gas-layer dT for both operating cases.
    for dt in (10, 20, 30, 50, 90):
        t_film = 273.15 + 85 + dt / 2.0   # surface-case film temp, conservative
        r = evaluate(dt, gap, t_film)
        flag = "" if r["correlation_band_ok"] else "  (Ra outside correlation band!)"
        print(f"{dt:>8.0f} {t_film:>10.1f} {r['Ra']:>12.3e} {r['Nu']:>7.3f} "
              f"{r['k_eff']:>12.4f}  {r['verdict']}{flag}")
    print("\nThreshold reference: Ra_c = 1708 for onset of convection in a")
    print("horizontal layer heated from below (verified, see project notes).")
