"""Surface-case derate sweep: max power that keeps every device < Tj limit.

Forced air is ruled out (30 y life, 10 y maintenance) and fins are the other
passive option; this script answers the third remedy -- DERATE: how far must
output power be reduced so the still-air surface case passes.

Physics it relies on (no new modelling): steady-state conduction with a
convective (Robin) boundary is LINEAR, so each node's rise above ambient scales
exactly with the loss magnitude. If every device loss is scaled by a factor f,
then  (Tj - T_amb)  scales by f. Hence the largest f that still satisfies
Tj <= T_limit for ALL devices is

    f_max = min_devices ( T_limit - T_amb ) / ( Tj_solved - T_amb )

read straight from one solved surface result. No re-solving, no Python physics
beyond reading the field and this ratio.

    python derate_surface.py        # reads results/surface.vtu

[ASSUMED] Scaling all device losses by one factor keeps the loss *distribution*
fixed. Real part-load shifts the split (efficiency varies with load), so treat
the output-power figure as a first-order derate, accurate near full load.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))

from paths import RESULTS
from config import CASES, GEOM, POWER_MAP_2SF, P_OUT, T_J_MAX_C, power_total

import vtk
from vtk.util.numpy_support import vtk_to_numpy

MM = 1000.0


def device_tj(vtu_path):
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


def main():
    vtu = os.path.join(RESULTS, "surface.vtu")
    if not os.path.exists(vtu):
        sys.exit("results/surface.vtu not found -- run the pipeline first.")
    t_amb = CASES["surface"].t_inf_c
    tj = device_tj(vtu)

    print("Surface derate (T_amb=%.0f C, limit=%.0f C, solved at P_out=%.0f W, "
          "loss=%.1f W)\n" % (t_amb, T_J_MAX_C, P_OUT, power_total()))
    print("  %-18s %8s %8s %8s" % ("device", "Tj[C]", "rise", "f_max"))
    f_limit, limiter = float("inf"), None
    for d in POWER_MAP_2SF:
        t = tj[d.name]
        if t is None:
            print("  %-18s   no FEM heat (check solve)" % d.name)
            continue
        rise = t - t_amb
        f = (T_J_MAX_C - t_amb) / rise if rise > 0 else float("inf")
        if f < f_limit:
            f_limit, limiter = f, d.name
        print("  %-18s %8.1f %8.1f %8.2f" % (d.name, t, rise, f))

    p_loss_max = f_limit * power_total()
    p_out_max = f_limit * P_OUT          # [ASSUMED] loss ~ proportional to output
    print("\n  Limiting device : %s" % limiter)
    print("  Max scale f_max : %.3f  (%s)" %
          (f_limit, "already passes at full power" if f_limit >= 1 else "derate needed"))
    print("  Max total loss  : %.1f W  (to keep all devices <= %.0f C)"
          % (p_loss_max, T_J_MAX_C))
    print("  ~Max output pwr : %.0f W  [first-order, loss prop. to output]"
          % p_out_max)


main()
