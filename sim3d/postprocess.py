"""
3D visualization of the solved temperature field (PyVista), styled like a
COMSOL / ANSYS thermal plot.

Two modes:

  python postprocess.py            # static PNGs: view_subsea.png, view_surface.png
  python postprocess.py --show     # interactive: BOTH cases side by side, with
                                   #   - an "overall efficiency" slider that
                                   #     rescales the field live, and
                                   #   - check-boxes to show/hide the cylindrical
                                   #     housing and the baseplate.

Live rescaling uses linear superposition: for a linear conduction problem with
fixed source distribution and constant convective BC, the temperature rise above
ambient scales with total loss, so  T = T_inf + P_loss * phi , where phi (deg C
per W) is taken from the solved field. Efficiency maps to loss by
P_loss = P_out * (1/eta - 1).  [ASSUMED: source distribution fixed as eta varies]

Reads result_*.vtk from solve.py and geometry/BCs from config.py.
"""

import sys
import numpy as np
import pyvista as pv

from config import (POWER_MAP_2SF, GEOM, CASES, power_total, OPERATING_POINT,
                    P_OUT, HOUSING_D, HOUSING_L, STAGE_LOSSES, T_J_MAX_C)

SHOW = "--show" in sys.argv
CMAP = "jet"                       # COMSOL/ANSYS rainbow
VTK = {"subsea": "result_subsea.vtk", "surface": "result_surface.vtk"}
P_REF = power_total()              # power at which the VTKs were solved


# ----------------------------------------------------------------------
# Data + helpers
# ----------------------------------------------------------------------
def _load(name):
    g = pv.read(VTK[name])
    tinf = CASES[name].t_inf_c
    phi = (g.point_data["T_C"] - tinf) / P_REF      # deg C per W
    return dict(name=name, grid=g, tinf=tinf, phi=phi)


P_AUX = STAGE_LOSSES[OPERATING_POINT]["flyback"]   # ~constant aux loss [W]


def _loss(load_w, eff_pct):
    """Total board loss for a given output load and overall efficiency.
    Non-aux loss scales with throughput; flyback aux is ~constant. [ASSUMED]"""
    eta = min(max(eff_pct, 1.0), 99.0) / 100.0
    return max(load_w * (1.0 / eta - 1.0), 0.0) + P_AUX


def _max_surface_load(case, eff_pct):
    """Output load at which this case's hottest point reaches T_J_MAX_C."""
    eta = min(max(eff_pct, 1.0), 99.0) / 100.0
    phi_max = float(case["phi"].max())
    p_loss_lim = (T_J_MAX_C - case["tinf"]) / phi_max
    return max((p_loss_lim - P_AUX) / (1.0 / eta - 1.0), 0.0)


def _field(case, p_loss):
    return case["tinf"] + p_loss * case["phi"]


def _housing_actor_mesh():
    return pv.Cylinder(center=(GEOM.board_len / 2, GEOM.y_wall_top / 2,
                               GEOM.board_wid / 2),
                       direction=(1, 0, 0),
                       radius=HOUSING_D / 2, height=HOUSING_L, resolution=48)


def _baseplate_actor_mesh():
    g = GEOM
    y0 = g.comp_h + g.pcb_t
    return pv.Box(bounds=(0, g.board_len, y0, y0 + g.base_t, 0, g.board_wid))


def _device_points():
    return np.array([[s.x_center, 0.5 * GEOM.comp_h, s.z_center]
                     for s in POWER_MAP_2SF])


def _device_labels(grid, field):
    ids = [grid.find_closest_point(p) for p in _device_points()]
    return [f"{s.name}\n{field[i]:.0f} C ({s.loss_w:.1f} W)"
            for s, i in zip(POWER_MAP_2SF, ids)]


# ----------------------------------------------------------------------
# Static PNG mode
# ----------------------------------------------------------------------
def _render_static(name):
    c = _load(name)
    grid = c["grid"]
    T = grid.point_data["T_C"]
    rng = [float(T.min()), float(T.max())]
    hot = grid.points[int(np.argmax(T))]
    bar = dict(title="Temperature (C)", vertical=True, title_font_size=18,
               label_font_size=14, n_labels=6, fmt="%.0f", position_x=0.86)

    p = pv.Plotter(off_screen=True, window_size=(1500, 650), shape=(1, 2))
    p.set_background("white")

    p.subplot(0, 0)
    p.add_mesh(grid, scalars="T_C", cmap=CMAP, clim=rng,
               smooth_shading=True, specular=0.3, scalar_bar_args=bar)
    p.add_point_labels([hot], [f"max {rng[1]:.0f} C"], font_size=14,
                       text_color="black", point_color="black", point_size=12,
                       shape_opacity=0.7, always_visible=True)
    p.show_bounds(grid="back", location="outer", xtitle="length x (m)",
                  ytitle="stack y (m)", ztitle="width z (m)", color="black")
    p.add_axes(color="black")
    p.add_text(f"{name.upper()} - exterior\n{OPERATING_POINT}, "
               f"{power_total():.0f} W | h={CASES[name].h} W/m2K, "
               f"Tinf={CASES[name].t_inf_c} C", font_size=11, color="black")

    p.subplot(0, 1)
    clip = grid.clip(normal="z", origin=grid.center)
    p.add_mesh(clip, scalars="T_C", cmap=CMAP, clim=rng,
               smooth_shading=True, scalar_bar_args=bar)
    p.add_point_labels(_device_points(), _device_labels(grid, T),
                       font_size=10, text_color="black", point_color="black",
                       point_size=8, shape_opacity=0.6, always_visible=True)
    p.add_axes(color="black")
    p.add_text(f"{name.upper()} - interior (z-cut), device temps",
               font_size=11, color="black")

    p.link_views()
    p.view_isometric()
    png = f"view_{name}.png"
    p.screenshot(png)
    p.close()
    return png, rng


# ----------------------------------------------------------------------
# Interactive dual-view with slider + toggles
# ----------------------------------------------------------------------
def _interactive():
    cases = {n: _load(n) for n in VTK}
    p = pv.Plotter(shape=(1, 2), window_size=(1700, 860), border=False)
    p.set_background("white")

    state = {"load": 300.0, "eff": 72.0}     # defaults ~ reference field (119.6 W)
    bar = dict(title="Temperature (C)", vertical=True, n_labels=6, fmt="%.0f",
               position_x=0.88, position_y=0.30, height=0.55, width=0.05)

    mesh_actor, grids, housing, base = {}, {}, {}, {}

    def _readout(n, c):
        f = grids[n]["T_C"]
        tmax = float(f.max())
        verdict = "PASS" if tmax <= T_J_MAX_C else "FAIL"
        loss = _loss(state["load"], state["eff"])
        txt = (f"load {state['load']:.0f} W   loss {loss:.0f} W\n"
               f"T_max {tmax:.0f} C   [{verdict} vs {T_J_MAX_C:.0f} C]")
        if n == "surface":
            txt += f"\nmax surface load @{state['eff']:.0f}% eff: " \
                   f"{_max_surface_load(c, state['eff']):.0f} W"
        return txt

    def _refresh():
        loss = _loss(state["load"], state["eff"])
        for col, (n, c) in enumerate(cases.items()):
            f = _field(c, loss)
            grids[n]["T_C"] = f
            mesh_actor[n].mapper.scalar_range = (float(f.min()), float(f.max()))
            p.subplot(0, col)
            p.add_point_labels(_device_points(), _device_labels(grids[n], f),
                               font_size=9, text_color="black",
                               point_color="black", point_size=6,
                               shape_opacity=0.5, always_visible=True,
                               name=f"lab_{n}")
            p.add_text(_readout(n, c), position="lower_left", font_size=10,
                       color="black", name=f"ro_{n}")
        p.render()

    loss0 = _loss(state["load"], state["eff"])
    for col, (n, c) in enumerate(cases.items()):
        p.subplot(0, col)
        g = c["grid"]
        g["T_C"] = _field(c, loss0)
        a = p.add_mesh(g, scalars="T_C", cmap=CMAP, smooth_shading=True,
                       scalar_bar_args=bar)
        a.mapper.scalar_range = (float(g["T_C"].min()), float(g["T_C"].max()))
        mesh_actor[n], grids[n] = a, g
        housing[n] = p.add_mesh(_housing_actor_mesh(), color="lightgray",
                                opacity=0.18, name=f"hou_{n}")
        base[n] = p.add_mesh(_baseplate_actor_mesh(), color="silver",
                             opacity=0.45, name=f"bas_{n}")
        p.add_point_labels(_device_points(), _device_labels(g, g["T_C"]),
                           font_size=9, text_color="black", point_color="black",
                           point_size=6, shape_opacity=0.5, always_visible=True,
                           name=f"lab_{n}")
        p.add_axes(color="black")
        p.add_text(f"{n.upper()}   h={CASES[n].h} W/m2K, Tinf={CASES[n].t_inf_c} C",
                   position="upper_left", font_size=12, color="black",
                   name=f"title_{n}")
        p.add_text(_readout(n, c), position="lower_left", font_size=10,
                   color="black", name=f"ro_{n}")
    p.link_views()
    p.view_isometric()

    def on_load(v):
        state["load"] = v
        _refresh()

    def on_eff(v):
        state["eff"] = v
        _refresh()

    def toggle_housing(flag):
        for n in cases:
            housing[n].SetVisibility(flag)
        p.render()

    def toggle_base(flag):
        for n in cases:
            base[n].SetVisibility(flag)
        p.render()

    # Two sliders along the bottom edge (load left, efficiency right).
    p.add_slider_widget(on_load, [0, P_OUT], value=state["load"],
                        title="Output load (W)",
                        pointa=(0.07, 0.07), pointb=(0.45, 0.07))
    p.add_slider_widget(on_eff, [60, 95], value=state["eff"],
                        title="Overall efficiency (%)",
                        pointa=(0.55, 0.07), pointb=(0.93, 0.07))
    # Visibility toggles, top-left corner.
    p.add_checkbox_button_widget(toggle_housing, value=True,
                                 position=(12, 812), size=26, color_on="gray")
    p.add_text("housing", position=(44, 814), font_size=9, color="black")
    p.add_checkbox_button_widget(toggle_base, value=True,
                                 position=(12, 778), size=26, color_on="silver")
    p.add_text("baseplate", position=(44, 780), font_size=9, color="black")
    p.show(title="SEM 300 W  -  subsea vs surface")


if __name__ == "__main__":
    if not SHOW and sys.platform.startswith("linux"):
        try:
            pv.start_xvfb()
        except Exception:
            pass
    if SHOW:
        _interactive()
    else:
        for n in VTK:
            png, rng = _render_static(n)
            print(f"{n:8s}: T[min/max] = {rng[0]:.1f}/{rng[1]:.1f} C  ->  {png}")
