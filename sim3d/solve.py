"""
3D steady-state conduction solver (SfePy) for the SEM 300 W module.

Weak form solved over the layered stack:
    int_Omega k grad(T).grad(s) dV
  + int_Gamma h (T - T_inf) s dS        (convective Robin BC, dw_bc_newton)
  - int_PCB  q s dV                     (volumetric device losses, dw_volume_lvf)
  = 0

Temperatures are carried in degrees Celsius: the model is linear (no
radiation), so the constant offset is irrelevant and results read directly.

Materials are assigned per mesh cell-group (1=fr4, 2=al, 3=tim, 4=ss316).
Device losses are injected through the PCB thickness under each footprint,
matching the convention of the validated 2D model. The top (component-side)
and the four edges are adiabatic; the housing outer face is convective. The
adiabatic top is justified by the Rayleigh gate: the sealed gas has
k_eff < 0.1 W/m.K, three orders below the metal path, so it carries
negligible heat.
"""

import numpy as np

from sfepy.discrete import (FieldVariable, Material, Integral, Function,
                            Equation, Equations, Problem)
from sfepy.discrete.fem import Mesh, FEDomain, Field
from sfepy.terms import Term
from sfepy.solvers.ls import ScipyDirect
from sfepy.solvers.nls import Newton
from sfepy.base.base import output as sfepy_output

from config import (MATERIALS, POWER_MAP_2SF, GEOM, CASES, power_total,
                    VIA_COUPLED, effective_h)
from mesh_gen import parametric_mesh, MAT_ID

sfepy_output.set_output(quiet=True)


def _sfepy_mesh():
    """Build a SfePy Mesh (with cell groups = material ids) from the
    parametric stack. Returns (mesh, y_layers, present_group_ids)."""
    points, hexes, mat, y_layers = parametric_mesh()
    ngroups = np.zeros(points.shape[0], dtype=np.int32)
    mesh = Mesh.from_data("sem_stack", points, ngroups,
                          [hexes], [mat], ["3_8"])
    return mesh, y_layers, sorted(np.unique(mat).tolist())


# Set per solve so the discretized source integrates to the nominal power
# exactly (corrects whole-cell vs pointwise-footprint quadrature mismatch).
# The scale is geometry-only (independent of the BC case), so it is cached.
_SRC_SCALE = 1.0
_SCALE_CACHE = {}


def _source_function(ts, coors, mode=None, **kwargs):
    """Volumetric heat source q [W/m^3] per quadrature point, from the
    2SF power map. Loss is generated inside the device blocks."""
    if mode != "qp":
        return
    q = np.zeros((coors.shape[0], 1, 1), dtype=np.float64)
    x, z = coors[:, 0], coors[:, 2]
    for s in POWER_MAP_2SF:
        vol = s.x_len * s.z_len * GEOM.comp_h
        inside = (np.abs(x - s.x_center) <= s.x_len / 2.0) & \
                 (np.abs(z - s.z_center) <= s.z_len / 2.0)
        q[inside, 0, 0] += s.loss_w / vol
    return {"val": _SRC_SCALE * q}


def solve_case(case_name: str, k_gas_eff: float | None = None):
    """Solve one operating case; return (temperatures, mesh, problem)."""
    case = CASES[case_name]
    mesh, yl, present = _sfepy_mesh()
    domain = FEDomain("domain", mesh)

    omega = domain.create_region("Omega", "all")
    inv = {gid: name for name, gid in MAT_ID.items()}
    names = [inv[g] for g in present]                  # only groups with cells
    reg = {name: domain.create_region(f"Omega_{name}",
                                      f"cells of group {MAT_ID[name]}")
           for name in names}
    # Convective face = outer housing wall (max y).
    gamma = domain.create_region(
        "GammaConv", f"vertices in (y > {yl['wall_top'] - 1e-6})", "facet")

    field = Field.from_args("temperature", np.float64, "scalar", omega,
                            approx_order=1)
    T = FieldVariable("T", "unknown", field)
    s = FieldVariable("s", "test", field, primary_var_name="T")

    integ = Integral("i", order=2)

    # Conductivity per material region (one Laplace term each).
    k_mats = {name: Material(f"k_{name}", values={"k": MATERIALS[name]["k"]})
              for name in names}
    cond_list = [
        Term.new(f"dw_laplace(k_{name}.k, s, T)", integ, reg[name],
                 **{f"k_{name}": k_mats[name], "s": s, "T": T})
        for name in names]
    cond_terms = cond_list[0]
    for t in cond_list[1:]:
        cond_terms = cond_terms + t

    # Convective Robin BC on the housing outer face (effective coefficient
    # folds in the full housing rejection area; see config.effective_h).
    h_eff = effective_h(case)
    conv = Material("conv", values={"h": h_eff, "tinf": case.t_inf_c})
    robin = Term.new("dw_bc_newton(conv.h, conv.tinf, s, T)", integ, gamma,
                     conv=conv, s=s, T=T)

    # Volumetric device losses generated inside the component blocks.
    src = Material("src", function=Function("src", _source_function))
    source = Term.new("dw_volume_lvf(src.val, s)", integ, reg["component"],
                      src=src, s=s)

    eq = Equation("balance", cond_terms + robin - source)
    pb = Problem("thermal", equations=Equations([eq]))
    pb.set_solver(Newton({}, lin_solver=ScipyDirect({})))

    # Two-pass normalization: coarse cells straddling a footprint edge drop
    # part of the nominal power, so the discretized source under-injects. The
    # discrete steady balance makes the wall heat-out equal exactly to the
    # injected power, so a unit-scale solve reveals the injected total; rescale
    # and re-solve so the full nominal power is delivered (energy-conservative
    # independent of footprint/mesh alignment).
    global _SRC_SCALE
    key = (VIA_COUPLED,)
    if key not in _SCALE_CACHE:
        _SRC_SCALE = 1.0
        pb.solve(save_results=False)
        area = pb.evaluate("ev_volume.2.GammaConv(T)", mode="eval")
        t_int = pb.evaluate("ev_integrate.2.GammaConv(T)", mode="eval")
        injected = h_eff * (t_int - case.t_inf_c * area)
        _SCALE_CACHE[key] = power_total() / injected
    _SRC_SCALE = _SCALE_CACHE[key]

    state = pb.solve(save_results=False)
    temps = state.get_state_parts()["T"]
    return temps, mesh, pb


def summarize(case_name, temps, mesh, yl):
    coors = mesh.coors
    wall = coors[:, 1] > yl["wall_top"] - 1e-6
    comp = coors[:, 1] < yl["comp_top"] + 1e-6     # component-side nodes
    return {
        "case": case_name,
        "T_max_C": float(temps.max()),
        "T_case_max_C": float(temps[comp].max()),
        "T_wall_mean_C": float(temps[wall].mean()),
        "T_min_C": float(temps.min()),
    }


if __name__ == "__main__":
    _, yl, _ = _sfepy_mesh()
    print("=" * 74)
    print(f"SEM 300 W 3D conduction solve | 2SF power map | "
          f"total {power_total():.1f} W")
    mount = ("via-coupled (k_via=%.0f W/mK)" % MATERIALS["via"]["k"]) \
        if VIA_COUPLED else "top-mount through FR-4 (worst case)"
    print(f"device coupling: {mount}")
    print("=" * 74)
    for cname in ("subsea", "surface"):
        temps, mesh, pb = solve_case(cname)
        out_vtk = f"result_{cname}.vtk"
        # Write the temperature field for ParaView/PyVista.
        import meshio
        _, hexes, _, _ = parametric_mesh()
        meshio.Mesh(mesh.coors, [("hexahedron", hexes)],
                    point_data={"T_C": temps}).write(out_vtk)
        r = summarize(cname, temps, mesh, yl)
        # Energy-balance verification: convective heat leaving the wall must
        # equal the injected power at steady state.
        area = pb.evaluate("ev_volume.2.GammaConv(T)", mode="eval")
        t_int = pb.evaluate("ev_integrate.2.GammaConv(T)", mode="eval")
        q_out = effective_h(CASES[cname]) * (t_int - CASES[cname].t_inf_c * area)
        bal_err = 100.0 * (q_out - power_total()) / power_total()
        print(f"\n[{cname}]  h={CASES[cname].h} W/m2K  T_inf={CASES[cname].t_inf_c} C")
        print(f"  T_case_max (device block) : {r['T_case_max_C']:7.2f} C")
        print(f"  T_wall_mean (outer)       : {r['T_wall_mean_C']:7.2f} C")
        print(f"  energy balance: Q_out={q_out:6.2f} W vs P={power_total():.2f} W"
              f"  (err {bal_err:+.2f} %)")
        print(f"  -> wrote {out_vtk}")
