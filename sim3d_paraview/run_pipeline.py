"""One-command Antmicro-style thermal pipeline: solve -> convert -> render.

    python run_pipeline.py                 # run all three stages
    python run_pipeline.py --from convert  # skip solving, start at .frd -> .vtu
    python run_pipeline.py --from render   # just re-render existing .vtu

Stage tools (each found via paths.find_exe, override with env vars):
    1. solve_cases.py   -> freecadcmd   (FreeCAD + CalculiX)        env FREECADCMD
    2. frd_to_vtu.py    -> this Python  (needs ccx2paraview)
    3. render_paraview.py -> pvpython   (ParaView)                  env PVPYTHON

Geometry note: this runs the parametric layered stack from ../sim3d/config.py.
To drive it from real CAD instead, see "Swapping in a STEP file" in solve_cases
usage below -- mesh_gen.gmsh_from_step() in ../sim3d already imports a STEP
assembly and tags each solid; point freecad_thermal at that geometry and the
rest of this pipeline is unchanged.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RESULTS, find_exe

STAGES = ("solve", "convert", "render", "report")


def _run(label, argv):
    print("\n=== %s: %s ===" % (label, " ".join(argv)))
    rc = subprocess.call(argv, cwd=HERE)
    if rc != 0:
        sys.exit("Stage '%s' failed (exit %d)." % (label, rc))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", choices=STAGES, default="solve",
                    help="stage to start from (default: solve)")
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    start = STAGES.index(args.start)

    if start <= STAGES.index("solve"):
        freecadcmd = find_exe("freecadcmd")
        if not freecadcmd:
            sys.exit("freecadcmd not found. Install FreeCAD 1.0 or set "
                     "FREECADCMD=/path/to/freecadcmd.")
        _run("solve", [freecadcmd, os.path.join(HERE, "solve_cases.py")])

    if start <= STAGES.index("convert"):
        # ccx2paraview runs in this same interpreter.
        _run("convert", [sys.executable, os.path.join(HERE, "frd_to_vtu.py")])

    if start <= STAGES.index("render"):
        pvpython = find_exe("pvpython")
        if not pvpython:
            sys.exit("pvpython not found. Install ParaView or set "
                     "PVPYTHON=/path/to/pvpython.")
        _run("render", [pvpython, os.path.join(HERE, "render_paraview.py")])

    if start <= STAGES.index("report"):
        # Device margin table reads the VTU with vtk in this same interpreter.
        _run("report", [sys.executable, os.path.join(HERE, "device_report.py")])

    print("\nPipeline complete. Artifacts in %s" % RESULTS)


if __name__ == "__main__":
    main()
