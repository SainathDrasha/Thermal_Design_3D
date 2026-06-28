"""Cross-check: 1-D thermal-resistance hand calc vs the CalculiX simulation.

A sanity check, not a second solver. It uses the SIM's own inputs (config.py),
so it is apples-to-apples with the FEM result -- unlike sem_thermal_corrected.py,
which is a richer network on a *different* loss set (4 devices, 102.6 W) and so
can't be compared device-by-device with the FEM (11 devices, 119.6 W).

For each case it computes:
  * The baseplate/housing bulk temperature from the external stack:
        T_base = T_amb + P_total * (R_conv + R_baseplate + R_TIM + R_wall)
    All device heat funnels through this shared path, so the FEM's coolest
    conductive nodes should sit near T_base. This validates the BC + solver.
  * Two 1-D bounds on each device junction temperature, added on top of T_base:
        R_fr4_full = t_pcb / (k_fr4 * footprint_area)      (surface source)
        R_fr4_half = 0.5 * R_fr4_full                      (source filling the
                                                            PCB thickness, as built)
    With NO lateral spreading these are UPPER bounds; the 3-D FEM spreads heat,
    so a correct solve must land at or below R_fr4_full and the FEM Tj should
    fall between T_base and (T_base + P*R_fr4_full). Outside that window points
    to a meshing/solver problem rather than the (known) missing via-coupling.

Run (project venv, needs vtk for the FEM read):
    python compare_analytical_vs_sim.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))

from paths import RESULTS
from config import (A_HOUSING, CASES, GEOM, MATERIALS, POWER_MAP_2SF,
                    T_J_MAX_C, power_total)

import vtk
from vtk.util.numpy_support import vtk_to_numpy

MM = 1000.0
A_FACE = GEOM.board_len * GEOM.board_wid
K_FR4 = MATERIALS["fr4"]["k"]


def external_resistance(case):
    """Series R from the baseplate to ambient (the path all heat shares)."""
    r_conv = 1.0 / (case.h * A_HOUSING)            # = 1/(h_eff * A_face)
    r_al = GEOM.base_t / (MATERIALS["al"]["k"] * A_FACE)
    r_tim = GEOM.tim_t / (MATERIALS["tim"]["k"] * A_FACE)
    r_ss = GEOM.wall_t / (MATERIALS["ss316"]["k"] * A_FACE)
    return r_conv + r_al + r_tim + r_ss


def sim_tj(vtu_path):
    """Peak FEM temperature (C) inside each device footprint."""
    r = vtk.vtkXMLUnstructuredGridReader()
    r.SetFileName(vtu_path)
    r.Update()
    g = r.GetOutput()
    pts = vtk_to_numpy(g.GetPoints().GetData())
    tc = vtk_to_numpy(g.GetPointData().GetArray("NT")) - 273.15
    out = {}
    y1 = GEOM.y_pcb_top * MM
    for d in POWER_MAP_2SF:
        m = ((abs(pts[:, 0] - d.x_center * MM) <= d.x_len / 2 * MM) &
             (abs(pts[:, 2] - d.z_center * MM) <= d.z_len / 2 * MM) &
             (pts[:, 1] >= -1e-6) & (pts[:, 1] <= y1 + 1e-6))
        out[d.name] = float(tc[m].max()) if m.any() else None
    return out, float(tc.min())


def main():
    for cname, case in CASES.items():
        vtu = os.path.join(RESULTS, cname + ".vtu")
        r_ext = external_resistance(case)
        t_base = case.t_inf_c + power_total() * r_ext
        print("\n" + "=" * 78)
        print("%s  (T_amb=%.0f C, h=%.0f)" % (cname.upper(), case.t_inf_c, case.h))
        print("  R_external = %.4f C/W  ->  predicted baseplate T_base = %.1f C"
              % (r_ext, t_base))
        if not os.path.exists(vtu):
            print("  (no %s.vtu yet -- run the pipeline to compare)" % cname)
            continue
        tj, tmin = sim_tj(vtu)
        print("  FEM coolest node = %.1f C  (expected ~T_base=%.1f C)  %s"
              % (tmin, t_base, "OK" if abs(tmin - t_base) < 0.35 * t_base + 8 else "CHECK"))
        print("  %-18s %6s %8s %8s %8s   %s"
              % ("device", "P[W]", "1Dhalf", "1Dfull", "FEM", "in-window?"))
        for d in POWER_MAP_2SF:
            r_full = GEOM.pcb_t / (K_FR4 * d.x_len * d.z_len)
            lo = t_base + d.loss_w * 0.5 * r_full
            hi = t_base + d.loss_w * r_full
            f = tj[d.name]
            if f is None:
                print("  %-18s %6.1f   --- no FEM heat (DROPPED) ---" % (d.name, d.loss_w))
                continue
            ok = "yes" if (t_base - 5) <= f <= (hi + 5) else ">>OUT<<"
            print("  %-18s %6.1f %8.0f %8.0f %8.0f   %s"
                  % (d.name, d.loss_w, lo, hi, f, ok))
    print("\nNotes: FEM between T_base and 1Dfull = solver consistent with the")
    print("modelled (no-via) FR-4 path. 'DROPPED' rows = the overlap bug (fixed in")
    print("freecad_thermal.py; re-run solve to refresh). Bottom-mount/with-via")
    print("design Tj (the real target) is far lower -- see sem_thermal_corrected.py.")


main()
