
import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from pathlib import Path

# Simple, fast 2D steady-state thermal simulation for the full SEM stack.
# Uses sparse linear algebra instead of slow Python loops so it does not appear to hang.
# Preferred library path remains FiPy / SfePy for local use, but this script is self-contained.

try:
    from scipy.sparse import lil_matrix
    from scipy.sparse.linalg import spsolve
except Exception as e:
    raise SystemExit('This script needs scipy installed: ' + str(e))


@dataclass
class Source:
    y_center: float
    y_len: float
    power_w: float
    name: str


def build_case(h_outer, T_inf, out_png):
    pcb_t = 0.00161
    base_t = 0.008
    tim_t = 0.00025
    wall_t = 0.010
    Lx = pcb_t + base_t + tim_t + wall_t
    Ly = 0.300
    width_z = 0.100

    nx = 56
    ny = 180
    dx = Lx / nx
    dy = Ly / ny

    x = np.linspace(dx/2, Lx-dx/2, nx)
    y = np.linspace(dy/2, Ly-dy/2, ny)
    X, Y = np.meshgrid(x, y, indexing='ij')

    k_fr4 = 0.30
    k_al = 160.0
    k_tim = 3.0
    k_ss = 16.0

    x1 = pcb_t
    x2 = pcb_t + base_t
    x3 = pcb_t + base_t + tim_t

    kmap = np.zeros((nx, ny))
    kmap[X <= x1] = k_fr4
    kmap[(X > x1) & (X <= x2)] = k_al
    kmap[(X > x2) & (X <= x3)] = k_tim
    kmap[X > x3] = k_ss

    sources = [
        Source(0.050, 0.016, 8.0, 'Buck SiC MOSFET'),
        Source(0.120, 0.014, 7.0, 'PFC MOSFET'),
        Source(0.190, 0.012, 4.0, 'DC/DC primary'),
        Source(0.250, 0.012, 3.5, 'DC/DC SR'),
    ]
    P_total = 102.6
    P_local = sum(s.power_w for s in sources)
    P_bg = max(P_total - P_local, 0.0)

    q = np.zeros((nx, ny))
    mask_bg = X <= pcb_t
    vol_bg = mask_bg.sum() * dx * dy * width_z
    q[mask_bg] += P_bg / vol_bg

    for s in sources:
        y0 = s.y_center - s.y_len/2
        y1 = s.y_center + s.y_len/2
        mask = (X <= pcb_t) & (Y >= y0) & (Y <= y1)
        vol = mask.sum() * dx * dy * width_z
        q[mask] += s.power_w / vol

    n = nx * ny
    A = lil_matrix((n, n))
    b = np.zeros(n)

    def idx(i, j):
        return i * ny + j

    for i in range(nx):
        for j in range(ny):
            p = idx(i, j)
            k = kmap[i, j]
            ap = 0.0

            # top boundary: adiabatic
            if i == 0:
                nb = idx(i + 1, j)
                coef = 2.0 * k / dx**2
                A[p, nb] = -coef
                ap += coef
            else:
                nb = idx(i - 1, j)
                coef = k / dx**2
                A[p, nb] = -coef
                ap += coef

            # bottom boundary: convection to ambient/fluid
            if i == nx - 1:
                nb = idx(i - 1, j)
                coef = k / dx**2
                A[p, nb] += -coef
                ap += coef + h_outer / dx
                b[p] += (h_outer / dx) * T_inf
            else:
                nb = idx(i + 1, j)
                coef = k / dx**2
                A[p, nb] += -coef
                ap += coef

            # left / right ends adiabatic
            if j == 0:
                nb = idx(i, j + 1)
                coef = 2.0 * k / dy**2
                A[p, nb] += -coef
                ap += coef
            else:
                nb = idx(i, j - 1)
                coef = k / dy**2
                A[p, nb] += -coef
                ap += coef

            if j == ny - 1:
                nb = idx(i, j - 1)
                coef = 2.0 * k / dy**2
                A[p, nb] += -coef
                ap += coef
            else:
                nb = idx(i, j + 1)
                coef = k / dy**2
                A[p, nb] += -coef
                ap += coef

            A[p, p] = ap
            b[p] += q[i, j]

    T = spsolve(A.tocsr(), b).reshape((nx, ny))

    top = T[0, :]
    outer = T[-1, :]

    summary = {
        'T_max': float(T.max()),
        'T_top_max': float(top.max()),
        'T_outer_max': float(outer.max()),
        'sources': []
    }
    for s in sources:
        j0 = int(np.argmin(np.abs(y - s.y_center)))
        summary['sources'].append((s.name, float(top[j0]), s.y_center * 1e3))

    output_path = Path(out_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(12, 4))
    extent = [0, Ly * 1e3, Lx * 1e3, 0]
    im = plt.imshow(T, aspect='auto', extent=extent, cmap='inferno')
    plt.colorbar(im, label='Temperature (°C)')
    plt.xlabel('Rail position y (mm)')
    plt.ylabel('Stack thickness x (mm)')
    plt.title(f'2D thermal field, h={h_outer} W/m²K, T∞={T_inf}°C')
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()

    return summary


output_dir = Path(__file__).resolve().parent / 'output'
output_dir.mkdir(parents=True, exist_ok=True)

surface = build_case(8.0, 85.0, str(output_dir / 'sem_surface_2d.png'))
subsea = build_case(100.0, 20.0, str(output_dir / 'sem_subsea_2d.png'))

report = []
report.append('Preferred industry-used Python libraries for a more formal version of this model:')
report.append('- FiPy: NIST finite-volume PDE solver in Python')
report.append('- SfePy: multi-material FEM heat-equation workflows')
report.append('This delivered script uses scipy sparse linear algebra to stay fast and avoid console hangs.')
report.append('')

for label, data in [('SURFACE', surface), ('SUBSEA', subsea)]:
    report.append(label)
    report.append(f"  Max temperature in stack   = {data['T_max']:.2f} °C")
    report.append(f"  Max PCB-top temperature    = {data['T_top_max']:.2f} °C")
    report.append(f"  Max outer-wall temperature = {data['T_outer_max']:.2f} °C")
    for name, tloc, ypos in data['sources']:
        report.append(f"  {name:<18} y={ypos:6.1f} mm -> local top temperature = {tloc:.2f} °C")
    report.append('')

(output_dir / 'sem_python_simulation_notes.txt').write_text('\n'.join(report))
print('\n'.join(report))
