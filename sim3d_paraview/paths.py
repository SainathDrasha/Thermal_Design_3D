"""Shared locations and external-tool discovery for the ParaView pipeline.

This sub-project is the Antmicro-style visualization tail bolted onto the
existing FreeCAD + CalculiX solver in ../sim3d. It adds nothing to the physics:
it solves with the existing model, converts CalculiX .frd results to VTU with
ccx2paraview, and renders them in ParaView. All paths and the (small) set of
external executables are resolved here so the stage scripts stay declarative.

Override any executable with an environment variable:
    FREECADCMD=/path/to/freecadcmd
    PVPYTHON=/path/to/pvpython
"""

import glob
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SIM3D = os.path.normpath(os.path.join(HERE, "..", "sim3d"))   # reused solver + config
RESULTS = os.path.join(HERE, "results")                       # all per-case artifacts

# The two operating environments defined in ../sim3d/config.py (CASES).
CASES = ("subsea", "surface")

# Executable candidates, in priority order: env override -> macOS app bundle
# (globbed for the version number) -> bare name on PATH. The first that exists
# wins. freecadcmd is FreeCAD's headless interpreter; pvpython is ParaView's.
_CANDIDATES = {
    "freecadcmd": [
        os.environ.get("FREECADCMD"),
        "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd",
        "/Applications/FreeCAD*.app/Contents/Resources/bin/freecadcmd",
        "freecadcmd",
    ],
    "pvpython": [
        os.environ.get("PVPYTHON"),
        "/Applications/ParaView*.app/Contents/bin/pvpython",
        "pvpython",
    ],
}


def find_exe(name):
    """Return the absolute path to an external tool, or None if not found.

    Accepts absolute paths, glob patterns (for versioned macOS app bundles) and
    bare command names resolved via PATH.
    """
    for cand in _CANDIDATES[name]:
        if not cand:
            continue
        if os.path.isabs(cand):
            matches = sorted(glob.glob(cand))
            if matches:
                return matches[-1]            # highest version if several
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None
