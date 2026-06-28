"""Mesh-convergence check for the FreeCAD + CalculiX thermal model.

Solves the SAME case at several mesh sizes (and quadratic vs linear elements)
and reports peak temperature vs node count, so the numerical (discretization)
error can be quantified separately from the modelling assumptions.

Run under FreeCAD's interpreter (the solves run here, not in the cloud sandbox):
    freecadcmd mesh_convergence.py

Reads nothing new -- reuses ../sim3d/freecad_thermal.py with its new mesh_mm /
second_order parameters. Edit CASE and CONFIGS below to taste. Finer meshes and
2nd-order take longer; start coarse.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))

from paths import RESULTS
import freecad_thermal as ft

CASE = "subsea"          # convergence trend is case-independent; subsea is clean
# (CharacteristicLengthMax mm, second_order?) -- coarse -> fine; last = reference
CONFIGS = [
    (4.0, False),
    (2.5, False),
    (1.5, False),
    (2.5, True),         # quadratic ~ acts like a much finer linear mesh
]


def main():
    out_dir = os.path.join(RESULTS, "_convergence")
    os.makedirs(out_dir, exist_ok=True)
    print("Mesh convergence -- case '%s'\n" % CASE)
    print("  %-8s %-8s %10s %10s" % ("mesh[mm]", "order", "nodes", "Tmax[C]"))
    runs = []
    for mesh_mm, second in CONFIGS:
        r = ft.solve_case(CASE, out_dir, mesh_mm=mesh_mm, second_order=second)
        runs.append((mesh_mm, second, r["n_nodes"], r["Tmax_C"]))
        print("  %-8.2f %-8s %10d %10.1f"
              % (mesh_mm, "2nd" if second else "1st", r["n_nodes"], r["Tmax_C"]))

    # Compare each run to the most-accurate (last) as the reference.
    ref_T = runs[-1][3]
    print("\nReference (finest/2nd order) Tmax = %.1f C" % ref_T)
    print("  %-8s %-8s %12s" % ("mesh[mm]", "order", "dTmax_vs_ref"))
    for mesh_mm, second, _, T in runs:
        print("  %-8.2f %-8s %+11.1f C" % (mesh_mm, "2nd" if second else "1st",
                                           T - ref_T))
    spread = max(r[3] for r in runs) - min(r[3] for r in runs)
    print("\nTotal Tmax spread across meshes: %.1f C" % spread)
    print("Small spread (and the last few runs converging) => low numerical "
          "error. A large spread means the result is still mesh-dependent "
          "(refine further / keep 2nd order).")


main()
