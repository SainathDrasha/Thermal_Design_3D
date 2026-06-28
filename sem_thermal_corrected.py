
import math
from dataclasses import dataclass


def c_to_k(t_c):
    return t_c + 273.15


def mm(x):
    return x * 1e-3


def cm2(x):
    return x * 1e-4


def fmt(v, nd=3):
    return f"{v:.{nd}f}"


def line():
    print("=" * 78)


def section(title):
    line()
    print(title)
    line()


@dataclass
class Device:
    name: str
    loss_w: float
    r_jc: float
    r_cs: float
    pad_w_mm: float
    pad_l_mm: float
    via_rows: int
    via_cols: int

    @property
    def pad_area_m2(self):
        return mm(self.pad_w_mm) * mm(self.pad_l_mm)

    @property
    def via_count(self):
        return self.via_rows * self.via_cols


# ======================================================================
# SECTION 1 — INPUTS
# ======================================================================
section("SECTION 1 — INPUTS AND WHAT THEY MEAN")
print(
    """
Geometry inputs
- PCB length/width define the available board and spreader footprint.
- PCB thickness is the total FR-4 stack thickness for through-plane conduction.
- Baseplate thickness is the aluminum spreader attached to the housing.
- Housing diameter/length/wall thickness define the outer rejection area and shell mass.
- TIM thickness and conductivity define the baseplate-to-housing contact layer.

Thermal-environment inputs
- h_air is natural air convection for hot surface commissioning.
- h_oil is the effective subsea oil-side convection coefficient.
- T_amb_surface is the hot air commissioning ambient.
- T_oil_subsea is the subsea fluid temperature.

PCB modeling inputs
- k_fr4_z is through-plane FR-4 conductivity.
- copper_spread_factor is a simple spreading multiplier that increases effective pad area
  to reflect copper pours and planes before heat enters the full chassis/baseplate.
- via conductivity is set separately for plated, hollow vias and optionally filled vias.

Operational inputs
- Operating points define total converter loss at each power/efficiency corner.
- Device losses define the local hotspots for junction temperature calculations.
"""
)

pcb_len = mm(300.0)
pcb_wid = mm(100.0)
pcb_area = pcb_len * pcb_wid
pcb_thickness_4l = mm(1.61)
pcb_thickness_6l = mm(1.62)
baseplate_thickness = mm(8.0)
baseplate_k = 160.0

tim_thickness = mm(0.25)
tim_k = 3.0

housing_len = mm(375.2)
housing_od = mm(125.0)
housing_wall = mm(10.0)
housing_k_ss316 = 16.0
housing_k_ti = 6.7
rho_ss316 = 7900.0
cp_ss316 = 500.0

k_fr4_z = 0.30
copper_spread_factor = 6.0

via_drill_mm = 0.30
via_plating_um = 25.0
via_k_plated = 320.0
via_fill_k_nonconductive = 0.8
via_fill_k_solder = 50.0

h_air = 8.0
h_oil = 100.0
h_n2 = 10.0
f_oil_wetted = 0.60
T_amb_surface = 85.0
T_oil_subsea = 20.0
T_j_max = 125.0
T_baseplate_limit = 105.0

loss_points = [
    ("300 W at 75% eff (worst corner)", 102.6),
    ("300 W at 86% avg eff", 51.5),
    ("150 W partial load", 31.2),
    ("50 W light load", 15.1),
]

buck = Device("Buck SiC MOSFET", 8.0, 0.40, 0.15, 16.0, 18.0, 5, 5)
pfc = Device("PFC MOSFET", 7.0, 0.50, 0.15, 14.0, 16.0, 5, 5)
dcdc_pri = Device("DC/DC primary MOSFET", 4.0, 0.50, 0.15, 12.0, 14.0, 4, 4)
dcdc_sr = Device("DC/DC SR MOSFET", 3.5, 0.60, 0.15, 12.0, 14.0, 4, 4)
devices = [buck, pfc, dcdc_pri, dcdc_sr]

print(f"PCB footprint                 = {pcb_len*1e3:.1f} mm × {pcb_wid*1e3:.1f} mm")
print(f"PCB area                      = {pcb_area*1e4:.1f} cm²")
print(f"4-layer / 6-layer thickness   = {pcb_thickness_4l*1e3:.2f} / {pcb_thickness_6l*1e3:.2f} mm")
print(f"Baseplate thickness           = {baseplate_thickness*1e3:.1f} mm")
print(f"Housing OD / length / wall    = {housing_od*1e3:.1f} / {housing_len*1e3:.1f} / {housing_wall*1e3:.1f} mm")
print(f"Natural air h                 = {h_air:.1f} W/m²K")
print(f"Subsea oil h                  = {h_oil:.1f} W/m²K")
print(f"FR-4 through-plane k          = {k_fr4_z:.2f} W/mK")
print(f"Plated via conductivity       = {via_k_plated:.0f} W/mK")
print(f"Copper spreading multiplier   = {copper_spread_factor:.1f}× local pad area")


# ======================================================================
# SECTION 2 — BASIC GEOMETRY AND OUTER CONVECTION
# ======================================================================
section("SECTION 2 — HOUSING AREAS, OUTER RESISTANCES, AND THERMAL MASS")

r_outer = housing_od / 2
r_inner = r_outer - housing_wall
A_lat = math.pi * housing_od * housing_len
A_oil = f_oil_wetted * A_lat
R_air_outer = 1.0 / (h_air * A_lat)
R_oil_outer = 1.0 / (h_oil * A_oil)
V_shell = math.pi * (r_outer**2 - r_inner**2) * housing_len
m_shell = V_shell * rho_ss316
mcp_shell = m_shell * cp_ss316

print(f"Outer lateral area A_lat      = {A_lat*1e4:.1f} cm²")
print(f"Oil-wetted area               = {A_oil*1e4:.1f} cm²")
print(f"R_air outer                   = {R_air_outer:.5f} °C/W")
print(f"R_oil outer                   = {R_oil_outer:.5f} °C/W")
print(f"SS316 shell mass              = {m_shell:.2f} kg")
print(f"SS316 shell heat capacity     = {mcp_shell:.0f} J/K")


# ======================================================================
# SECTION 3 — WHOLE-BOARD LUMPED REQUIREMENT (kept for budgeting)
# ======================================================================
section("SECTION 3 — WHOLE-BOARD LUMPED R_ba REQUIREMENT")
print("This section is retained as a top-level requirement filter only.")
print("It is useful for board-to-ambient budgeting, but not sufficient for local hotspot sign-off.")
print()

for name, p_loss in loss_points:
    r_ba = (T_baseplate_limit - T_amb_surface) / p_loss
    print(f"{name:<34}  P_loss = {p_loss:>6.1f} W   Required R_ba = {r_ba:.3f} °C/W")


# ======================================================================
# SECTION 4 — FOUNDATIONAL CORRECTION: LOCAL SPREADING VS WHOLE BOARD
# ======================================================================
section("SECTION 4 — LOCAL FR-4 THROUGH-PLANE RESISTANCE (CORRECTED MODEL)")
print("The earlier whole-board FR-4 resistance used the full 300×100 mm area.")
print("That is optimistic for a discrete hot component. This corrected model compares:")
print("- Unrealistic whole-board area")
print("- Pure local pad area")
print("- Local area with copper spreading multiplier")
print()


def r_cond(t, k, area):
    return t / (k * area)


def effective_spread_area(device, total_limit_area, spread_factor):
    return min(device.pad_area_m2 * spread_factor, total_limit_area)

for stack_name, tpcb in [("4-layer", pcb_thickness_4l), ("6-layer", pcb_thickness_6l)]:
    print(f"{stack_name}")
    r_whole = r_cond(tpcb, k_fr4_z, pcb_area)
    print(f"  Whole-board FR-4 R_z        = {r_whole:.4f} °C/W  [optimistic lower bound]")
    for d in devices:
        a_local = d.pad_area_m2
        a_spread = effective_spread_area(d, pcb_area, copper_spread_factor)
        r_local = r_cond(tpcb, k_fr4_z, a_local)
        r_spread = r_cond(tpcb, k_fr4_z, a_spread)
        print(f"  {d.name:<24} pad={a_local*1e6:6.1f} mm²  R_local={r_local:7.2f} °C/W  R_spread={r_spread:6.2f} °C/W")
    print()


# ======================================================================
# SECTION 5 — VIA PHYSICS: HOLLOW, NON-CONDUCTIVE FILL, SOLDER-FILL
# ======================================================================
section("SECTION 5 — THERMAL VIA MODEL WITH REALISTIC VIA PROPERTY CASES")

via_drill = mm(via_drill_mm)
via_plating = via_plating_um * 1e-6
via_outer_r = via_drill / 2 + via_plating
via_inner_r = via_drill / 2
via_barrel_area = math.pi * (via_outer_r**2 - via_inner_r**2)
via_core_area = math.pi * via_inner_r**2

print(f"Via drill diameter            = {via_drill_mm:.2f} mm")
print(f"Plating thickness             = {via_plating_um:.0f} µm")
print(f"Via barrel copper area        = {via_barrel_area*1e12:.0f} µm²")
print(f"Via inner core area           = {via_core_area*1e12:.0f} µm²")
print()


def via_resistance(tpcb, k_barrel, fill_mode="hollow"):
    g_barrel = k_barrel * via_barrel_area / tpcb
    g_fill = 0.0
    if fill_mode == "nonconductive_fill":
        g_fill = via_fill_k_nonconductive * via_core_area / tpcb
    elif fill_mode == "solder_fill":
        g_fill = via_fill_k_solder * via_core_area / tpcb
    g_total = g_barrel + g_fill
    return 1.0 / g_total

for stack_name, tpcb in [("4-layer", pcb_thickness_4l), ("6-layer", pcb_thickness_6l)]:
    print(f"{stack_name}")
    rv_hollow = via_resistance(tpcb, via_k_plated, "hollow")
    rv_noncond = via_resistance(tpcb, via_k_plated, "nonconductive_fill")
    rv_solder = via_resistance(tpcb, via_k_plated, "solder_fill")
    print(f"  Single via, hollow plated          = {rv_hollow:.1f} °C/W")
    print(f"  Single via, non-conductive filled  = {rv_noncond:.1f} °C/W")
    print(f"  Single via, solder-filled          = {rv_solder:.1f} °C/W")
    for d in devices:
        print(f"  {d.name:<24}  count={d.via_count:>2d}  R_array hollow={rv_hollow/d.via_count:6.2f}  solder-filled={rv_solder/d.via_count:6.2f} °C/W")
    print()


# ======================================================================
# SECTION 6 — CORRECTED TOP-MOUNT PATH: PAD + VIA ARRAY + BASEPLATE
# ======================================================================
section("SECTION 6 — CORRECTED TOP-MOUNT DEVICE THERMAL PATH")
print("This section corrects the earlier optimistic whole-board model.")
print("The top-mount path is modeled as:")
print("junction -> case -> interface -> local pad spreading -> via array -> baseplate/housing")
print()


def top_mount_tj(device, tpcb, outer_r_total, fill_mode):
    a_spread = effective_spread_area(device, pcb_area, copper_spread_factor)
    r_pad = r_cond(tpcb, k_fr4_z, a_spread)
    r_via_single = via_resistance(tpcb, via_k_plated, fill_mode)
    r_vias = r_via_single / device.via_count
    return T_amb_surface + device.loss_w * (device.r_jc + device.r_cs + r_pad + r_vias + outer_r_total), r_pad, r_vias

outer_r_ss_air = R_air_outer + r_cond(housing_wall, housing_k_ss316, pcb_area) + r_cond(tim_thickness, tim_k, pcb_area) + r_cond(baseplate_thickness, baseplate_k, pcb_area)

for stack_name, tpcb in [("4-layer", pcb_thickness_4l), ("6-layer", pcb_thickness_6l)]:
    print(f"{stack_name}")
    for fill_mode in ["hollow", "solder_fill"]:
        label = "hollow vias" if fill_mode == "hollow" else "solder-filled vias"
        print(f"  {label}")
        for d in devices:
            tj, r_pad, r_vias = top_mount_tj(d, tpcb, outer_r_ss_air, fill_mode)
            margin = T_j_max - tj
            stat = "✓" if margin >= 0 else "FAIL"
            print(f"    {d.name:<24} Tj={tj:6.1f}°C  margin={margin:6.1f}°C  R_pad={r_pad:5.2f}  R_vias={r_vias:5.2f}  {stat}")
    print()


# ======================================================================
# SECTION 7 — BOTTOM-MOUNT DIRECT TO BASEPLATE/RAIL
# ======================================================================
section("SECTION 7 — BOTTOM-MOUNT DIRECT-TO-BASEPLATE MODEL")
print("Bottom-mount removes most PCB through-plane and via bottlenecks.")
print("This is the preferred high-confidence path for hotspot devices.")
print()

R_outer_subsea = R_oil_outer + r_cond(housing_wall, housing_k_ss316, pcb_area) + r_cond(tim_thickness, tim_k, pcb_area) + r_cond(baseplate_thickness, baseplate_k, pcb_area)
R_outer_surface = R_air_outer + r_cond(housing_wall, housing_k_ss316, pcb_area) + r_cond(tim_thickness, tim_k, pcb_area) + r_cond(baseplate_thickness, baseplate_k, pcb_area)

for env_name, Tamb, Router in [("Subsea oil-coupled", T_oil_subsea, R_outer_subsea), ("Surface natural air", T_amb_surface, R_outer_surface)]:
    print(env_name)
    for d in devices:
        tj = Tamb + 102.6 * Router + d.loss_w * (d.r_jc + d.r_cs)
        margin = T_j_max - tj
        stat = "✓" if margin >= 0 else "FAIL"
        print(f"  {d.name:<24} Tj={tj:6.1f}°C  margin={margin:6.1f}°C  {stat}")
    print()


# ======================================================================
# SECTION 8 — DISTRIBUTED RAIL / CHASSIS HOTSPOT CHECK
# ======================================================================
section("SECTION 8 — SIMPLE DISTRIBUTED RAIL HOTSPOT CHECK")
print("The earlier lumped chassis model assumed an isothermal rail.")
print("This section adds a simple 1D distributed check with four heat sources along the 300 mm rail.")
print()

rail_len = pcb_len
rail_w = pcb_wid
rail_t = baseplate_thickness
rail_k = baseplate_k
source_x = [0.05, 0.12, 0.19, 0.25]
source_p = [d.loss_w for d in devices]
seg_positions = [0.0] + source_x + [rail_len]
A_rail_axial = rail_w * rail_t

segments = []
for i in range(len(seg_positions)-1):
    dx = seg_positions[i+1] - seg_positions[i]
    if dx <= 0:
        continue
    r_seg = dx / (rail_k * A_rail_axial)
    segments.append((dx, r_seg))

print("Axial rail segments:")
for i, (dx, rseg) in enumerate(segments, 1):
    print(f"  Segment {i}: dx={dx*1e3:6.1f} mm  R_axial={rseg:.5f} °C/W")
print()

T_outer_uniform_subsea = T_oil_subsea + 102.6 * R_outer_subsea
T_outer_uniform_surface = T_amb_surface + 102.6 * R_outer_surface

for env_name, Tbase in [("Subsea", T_outer_uniform_subsea), ("Surface", T_outer_uniform_surface)]:
    print(env_name)
    cumulative_left = 0.0
    for i, d in enumerate(devices):
        left_heat = sum(source_p[:i])
        right_heat = sum(source_p[i+1:])
        local_r = 0.0
        for j in range(i):
            local_r += segments[j][1]
        delta_local = left_heat * local_r * 0.5 + right_heat * local_r * 0.15
        t_local = Tbase + delta_local
        print(f"  {d.name:<24} local base estimate = {t_local:6.2f}°C  hotspot rise above lumped ≈ {delta_local:4.2f}°C")
    print()


# ======================================================================
# SECTION 9 — SURFACE CASE IMPROVEMENTS EARLIER DISCUSSED
# ======================================================================
section("SECTION 9 — SURFACE IMPROVEMENT OPTIONS")

R_internal_equiv = 0.80 * (r_cond(housing_wall, housing_k_ss316, pcb_area) + r_cond(tim_thickness, tim_k, pcb_area) + r_cond(baseplate_thickness, baseplate_k, pcb_area)) + 0.08 * (buck.r_jc + buck.r_cs)
R_total_surface = R_air_outer + R_internal_equiv
P_max_surface = (T_j_max - T_amb_surface) / R_total_surface
P_out_75 = P_max_surface * 0.75 / 0.25
P_out_86 = P_max_surface * 0.86 / 0.14
A_needed = 1.0 / (h_air * ((T_j_max - T_amb_surface)/102.6 - R_internal_equiv))

print(f"Surface outer convection dominates: R_air = {R_air_outer:.5f} °C/W")
print(f"Maximum dissipation in 85°C still air = {P_max_surface:.1f} W")
print(f"Equivalent output at 75% / 86% eff    = {P_out_75:.0f} W / {P_out_86:.0f} W")
print(f"Area needed for 102.6 W in air        = {A_needed*1e4:.0f} cm²  ({A_needed/A_lat:.2f}× current outer area)")
print()
print("Water-bath / oil-bath style commissioning check:")
for label, h_ext in [("Natural air", 8.0), ("SCM oil", 100.0), ("Still water", 500.0), ("Water slight flow", 2000.0)]:
    r_ext = 1.0 / (h_ext * A_lat)
    tj = T_amb_surface + 102.6 * (r_ext + r_cond(housing_wall, housing_k_ss316, pcb_area) + r_cond(tim_thickness, tim_k, pcb_area) + r_cond(baseplate_thickness, baseplate_k, pcb_area)) + buck.loss_w * (buck.r_jc + buck.r_cs)
    margin = T_j_max - tj
    stat = "✓" if margin >= 0 else "FAIL"
    print(f"  {label:<18}  Tj_worst={tj:6.1f}°C  margin={margin:6.1f}°C  {stat}")


# ======================================================================
# SECTION 10 — THERMAL MASS BUFFER INCLUDING HOUSING + BASEPLATE + PCB
# ======================================================================
section("SECTION 10 — THERMAL MASS BUFFER FOR SURFACE COMMISSIONING")

rho_al = 2700.0
cp_al = 900.0
V_bp = pcb_area * baseplate_thickness
m_bp = rho_al * V_bp
mcp_bp = m_bp * cp_al

rho_fr4 = 1900.0
cp_fr4 = 1100.0
rho_cu = 8900.0
cp_cu = 385.0
pcb_stack_total = pcb_area * mm(1.6)
v_cu = pcb_stack_total * 0.20
v_fr4 = pcb_stack_total * 0.80
mcp_pcb = v_fr4 * rho_fr4 * cp_fr4 + v_cu * rho_cu * cp_cu
mcp_comp = 400.0
mcp_total = mcp_shell + mcp_bp + mcp_pcb + mcp_comp
E_budget = mcp_total * (T_j_max - T_amb_surface)
Q_reject = h_air * A_lat * (T_j_max - T_amb_surface)
net_100w = 102.6 - Q_reject
safe_time_min = E_budget / net_100w / 60.0

print(f"SS316 shell mcp                = {mcp_shell:.0f} J/K")
print(f"Baseplate mcp                 = {mcp_bp:.0f} J/K")
print(f"PCB effective mcp             = {mcp_pcb:.0f} J/K")
print(f"Component allowance mcp       = {mcp_comp:.0f} J/K")
print(f"Total mcp                     = {mcp_total:.0f} J/K")
print(f"Stored energy to 40°C rise    = {E_budget/1000:.1f} kJ")
print(f"Passive rejection at 40°C rise= {Q_reject:.1f} W")
print(f"Net heating at 102.6 W loss   = {net_100w:.1f} W")
print(f"Estimated safe time           = {safe_time_min:.0f} min")


# ======================================================================
# SECTION 11 — DESIGN CONCLUSIONS
# ======================================================================
section("SECTION 11 — DESIGN CONCLUSIONS")
print("1. The previous whole-board FR-4 model is valid only as a lower-bound optimism check.")
print("2. Local spreading under each hotspot must be modeled with local pad area plus copper spreading.")
print("3. Hollow plated vias are a weak path; filled vias help, but do not fully rescue top-mount devices in hot air.")
print("4. Bottom-mount direct-to-baseplate remains the preferred power-device architecture.")
print("5. The rail/chassis should not be treated as perfectly isothermal for final sign-off.")
print("6. Surface operation in 85°C still air requires derating, temporary liquid coupling, or time-limited commissioning.")
print("7. Subsea oil-coupled operation remains the primary continuous operating condition.")
