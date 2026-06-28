"""Stage 1 (FreeCAD + CalculiX): solve each case, snapshot its .frd.

Run under FreeCAD's own interpreter:
    freecadcmd solve_cases.py

This reuses ../sim3d/freecad_thermal.py unchanged: Python builds only the
geometry and the physical inputs; FreeCAD meshes (Gmsh) and CalculiX solves the
steady-state conduction problem. CalculiX (via ccxtools) always writes its
result as "Mesh.frd" and overwrites it every run, so this driver copies it to
results/<case>.frd right after each solve, giving one named result per case for
the downstream ParaView stages.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                # paths.py
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))   # freecad_thermal.py, config.py

from paths import CASES, RESULTS
import freecad_thermal as ft

print("solve_cases.py: starting", flush=True)


def main():
    os.makedirs(RESULTS, exist_ok=True)
    print("Solving %d case(s) into %s" % (len(CASES), RESULTS))
    for case in CASES:
        # freecad_thermal owns all geometry/mesh/solve; results land in RESULTS.
        r = ft.solve_case(case, RESULTS)
        mesh_frd = os.path.join(RESULTS, "Mesh.frd")
        if not os.path.exists(mesh_frd):
            raise RuntimeError(
                "CalculiX produced no Mesh.frd for '%s' (check Mesh.cvg/.sta in %s)"
                % (case, RESULTS))
        shutil.copy2(mesh_frd, os.path.join(RESULTS, case + ".frd"))
        print("[solve] %-8s Tmax=%.1f C  h_eff=%.1f W/m2K  nodes=%d -> %s.frd"
              % (case, r["Tmax_C"], r["h_eff_W_m2K"], r["n_nodes"], case))
    print("Done. Per-case .frd files written; run frd_to_vtu.py next.")


# Called unconditionally: freecadcmd does not reliably set __name__=="__main__"
# for a script passed on the command line, so a guarded call would be skipped.
# This file is only ever an entry point (never imported), so this is safe.
main()
