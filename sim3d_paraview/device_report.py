"""Stage 4: per-device junction-temperature margin table (CSV).

For each results/<case>.vtu this reports, for every device in the power map,
the peak temperature inside its footprint volume -- which IS the device
junction temperature in this model, where each device's loss is injected as a
volumetric source in the PCB -- the margin to the Tj limit, and a PASS/FAIL
verdict. It only reads and tabulates the CalculiX field (unit shift K->C); no
physics is recomputed in Python, per project rule.

    python device_report.py        # -> results/device_margins.csv

[ASSUMED] One junction limit (config.T_J_MAX_C = 125 C) is applied to every
device. Real parts differ (SiC ~175 C, magnetics/electrolytics often lower);
edit LIMITS below if you have per-device ratings.
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))

from paths import CASES, RESULTS
from config import CASES as CASE_BC, GEOM, POWER_MAP_2SF, T_J_MAX_C

import vtk
from vtk.util.numpy_support import vtk_to_numpy

MM = 1000.0

# Per-device Tj limit (C). Default: the single design limit for all devices.
LIMITS = {dev.name: T_J_MAX_C for dev in POWER_MAP_2SF}


def _read_field(vtu_path):
    """Return (points_mm Nx3, temperature_C N) from a results VTU."""
    r = vtk.vtkXMLUnstructuredGridReader()
    r.SetFileName(vtu_path)
    r.Update()
    g = r.GetOutput()
    pts = vtk_to_numpy(g.GetPoints().GetData())               # mm
    nt = vtk_to_numpy(g.GetPointData().GetArray("NT")) - 273.15  # K -> C
    return pts, nt


def _device_peak_c(pts, temp_c, dev):
    """Peak temperature among field points inside a device's footprint volume."""
    x0 = (dev.x_center - dev.x_len / 2.0) * MM
    x1 = (dev.x_center + dev.x_len / 2.0) * MM
    z0 = (dev.z_center - dev.z_len / 2.0) * MM
    z1 = (dev.z_center + dev.z_len / 2.0) * MM
    y0, y1 = 0.0, GEOM.y_pcb_top * MM          # PCB heat-injection layer
    inside = ((pts[:, 0] >= x0) & (pts[:, 0] <= x1) &
              (pts[:, 1] >= y0) & (pts[:, 1] <= y1) &
              (pts[:, 2] >= z0) & (pts[:, 2] <= z1))
    if not inside.any():
        return None
    return float(temp_c[inside].max())


def main():
    wrote = 0
    for case in CASES:
        vtu = os.path.join(RESULTS, case + ".vtu")
        if not os.path.exists(vtu):
            print("[report] %s.vtu missing -- run the solve/convert stages first" % case)
            continue
        pts, temp_c = _read_field(vtu)
        t_amb = CASE_BC[case].t_inf_c
        print("\n%s (ambient %.0f C):" % (case, t_amb))
        print("  %-18s %8s %8s %8s %8s  %s"
              % ("device", "P[W]", "Tj[C]", "dT[C]", "margin", "verdict"))
        rows = []
        for dev in POWER_MAP_2SF:
            tj = _device_peak_c(pts, temp_c, dev)
            if tj is None:
                continue
            limit = LIMITS[dev.name]
            margin = limit - tj
            verdict = "PASS" if margin >= 0 else "FAIL"
            rows.append({
                "device": dev.name, "P_loss_W": round(dev.loss_w, 2),
                "Tj_C": round(tj, 1), "ambient_C": t_amb,
                "deltaT_C": round(tj - t_amb, 1), "limit_C": limit,
                "margin_C": round(margin, 1), "verdict": verdict,
            })
            print("  %-18s %8.1f %8.1f %8.1f %8.1f  %s"
                  % (dev.name, dev.loss_w, tj, tj - t_amb, margin, verdict))
        if not rows:
            continue
        # One CSV per case: results/<case>_margins.csv
        out_csv = os.path.join(RESULTS, "%s_margins.csv" % case)
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
        print("  -> wrote %s (%d devices, %d FAIL)"
              % (os.path.basename(out_csv), len(rows), n_fail))
        wrote += 1
    if not wrote:
        sys.exit("No results to report.")


main()
