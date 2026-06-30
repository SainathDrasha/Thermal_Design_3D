"""Labeled board thermal map per case -- the clearest "what is each device".

Top-down view of the 300 x 100 mm PCB: every device drawn as a box at its real
position, labeled name / loss / simulated peak temperature, coloured by that
temperature. Generated for BOTH cases automatically by run_pipeline.py.

    python board_map.py            # -> results/<case>_board_map.png

Reads only the solved field (NT) and tabulates per-device peaks -- no physics
recomputed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))

from paths import CASES, RESULTS
from config import CASES as CASE_BC, GEOM, POWER_MAP_2SF, T_J_MAX_C

import vtk
from vtk.util.numpy_support import vtk_to_numpy
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import cm
from matplotlib.colors import Normalize

MM = 1000.0


def _sim_tj(vtu_path):
    """Peak temperature (C) inside each device footprint, by device name."""
    r = vtk.vtkXMLUnstructuredGridReader()
    r.SetFileName(vtu_path)
    r.Update()
    g = r.GetOutput()
    pts = vtk_to_numpy(g.GetPoints().GetData())
    tc = vtk_to_numpy(g.GetPointData().GetArray("NT")) - 273.15
    y1 = GEOM.y_pcb_top * MM
    out = {}
    for d in POWER_MAP_2SF:
        m = ((abs(pts[:, 0] - d.x_center * MM) <= d.x_len / 2 * MM) &
             (abs(pts[:, 2] - d.z_center * MM) <= d.z_len / 2 * MM) &
             (pts[:, 1] <= y1 + 1e-6))
        out[d.name] = float(tc[m].max()) if m.any() else None
    return out


def board_map(case):
    vtu = os.path.join(RESULTS, case + ".vtu")
    if not os.path.exists(vtu):
        print("[map] %s.vtu missing -- run the solve/convert stages first" % case)
        return False
    sim = _sim_tj(vtu)
    t_amb = CASE_BC[case].t_inf_c
    vals = [v for v in sim.values() if v is not None]
    norm = Normalize(min(vals), max(vals))
    cmap = cm.turbo

    fig, ax = plt.subplots(figsize=(13, 5.4))
    ax.add_patch(Rectangle((0, 0), GEOM.board_len * MM, GEOM.board_wid * MM,
                           fc="#efefef", ec="k", lw=1.5))
    for d in POWER_MAP_2SF:
        x = (d.x_center - d.x_len / 2) * MM
        z = (d.z_center - d.z_len / 2) * MM
        w, h = d.x_len * MM, d.z_len * MM
        t = sim[d.name]
        if t is None:
            ax.add_patch(Rectangle((x, z), w, h, fc="#dddddd", ec="red",
                                   lw=2, hatch="xx"))
            txt = "%s\n%.0f W\nno heat" % (d.name.replace("_", " "), d.loss_w)
            ax.text(d.x_center * MM, d.z_center * MM, txt, ha="center",
                    va="center", fontsize=7, color="red")
        else:
            over = t > T_J_MAX_C
            pad = d.cooling == "pad"
            ax.add_patch(Rectangle((x, z), w, h, fc=cmap(norm(t)),
                                   ec=("red" if over else "k"),
                                   lw=(2.0 if over else 1.0),
                                   ls=("--" if pad else "-")))
            tag = "  (pad)" if pad else ""
            txt = "%s%s\n%.0f W\n%.0f C" % (d.name.replace("_", " "), tag,
                                           d.loss_w, t)
            ax.text(d.x_center * MM, d.z_center * MM, txt, ha="center",
                    va="center", fontsize=7,
                    color=("white" if norm(t) > 0.6 else "black"))
    ax.set_xlim(-8, GEOM.board_len * MM + 8)
    ax.set_ylim(-8, GEOM.board_wid * MM + 8)
    ax.set_aspect("equal")
    ax.set_xlabel("board length  x  [mm]")
    ax.set_ylabel("width z [mm]")
    ax.set_title("SEM 300W -- %s (coolant %.0f C): device peak temp "
                 "(red edge = over %.0f C; dashed = pad-mounted magnetic)"
                 % (case.upper(), t_amb, T_J_MAX_C), fontsize=10.5)
    cb = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
                      fraction=0.025, pad=0.01)
    cb.set_label("simulated Tj [C]")
    png = os.path.join(RESULTS, case + "_board_map.png")
    fig.savefig(png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("[map] %-8s -> %s_board_map.png  (Tmax %.0f C)"
          % (case, case, max(vals)))
    return True


def main():
    done = False
    for case in CASES:
        done |= board_map(case)
    if not done:
        sys.exit("No results to map.")


main()
