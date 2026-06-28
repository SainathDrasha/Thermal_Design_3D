"""Stage 2: convert each results/<case>.frd to <case>.vtu with ccx2paraview.

Run with the same Python that has ccx2paraview installed (your project venv):
    pip install 'ccx2paraview[VTK]'
    python frd_to_vtu.py

ccx2paraview is the official CalculiX->Paraview converter. It writes the VTU
next to the input file with the same basename (results/<case>.vtu). The result
carries the nodal temperature as point array 'NT' (in Kelvin, the unit fed to
CalculiX) and the heat-flux vector as 'FLUX' -- both straight from the solver.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import CASES, RESULTS


def convert(frd_path):
    """Convert one .frd to .vtu in place (same basename)."""
    from ccx2paraview import Converter
    Converter(frd_path, ["vtu"]).run()


def main():
    missing = 0
    for case in CASES:
        frd = os.path.join(RESULTS, case + ".frd")
        if not os.path.exists(frd):
            print("[convert] %s.frd not found -- run solve_cases.py first" % case)
            missing += 1
            continue
        convert(frd)
        print("[convert] %s.frd -> %s.vtu" % (case, case))
    if missing:
        sys.exit(1)
    print("Done. Run render_paraview.py next (under pvpython).")


if __name__ == "__main__":
    main()
