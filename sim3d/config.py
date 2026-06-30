"""
Central configuration for the SEM 300 W 3D thermal pipeline.

Single source of truth for materials, geometry, the 2SF worst-case power map,
and the two operating-environment boundary conditions. Every solver/mesh stage
imports from here so a parameter is changed in exactly one place.

All values are SI (m, W, K unless a name says _c for Celsius).

Provenance tags:
  [DOC]      taken from the project markdown / verified hand calculation
  [2D]       reused from the existing sem_python_heat_sim.py 2D model
  [ASSUMED]  an intra-stage split or placeholder that must be confirmed,
             flagged per project rule "any assumptions must be flagged".
"""

from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# Materials: thermal conductivity (W/m.K)
# ----------------------------------------------------------------------
# FR-4 here is the through-plane (z) value; in-plane is ~10x higher but the
# limiting path for a top-mounted device is through-plane.  [2D][DOC]
MATERIALS = {
    "fr4":   {"k": 0.30,  "desc": "PCB FR-4, through-plane"},          # [2D]
    "al":    {"k": 160.0, "desc": "Aluminium baseplate/spreader"},     # [2D]
    "tim":   {"k": 3.0,   "desc": "Thermal interface material"},        # [2D]
    "ss316": {"k": 16.0,  "desc": "SS316L housing wall"},               # [2D]
    # Gas conductivity uses the Rayleigh-gate effective value (folds in weak
    # natural convection); molecular k is ~0.026.  [DOC]+rayleigh.py
    "gas":   {"k": 0.06,  "desc": "Sealed internal gas (N2), effective k_eff"},
    # Device package lumped conductivity (case-to-board). [ASSUMED]
    "component": {"k": 20.0, "desc": "Power-device package, lumped"},
    # Through-PCB thermal-via column under a device pad. k is computed below
    # from the via copper fill fraction (see K_VIA).
    "via":   {"k": None,   "desc": "Filled thermal-via array, through-plane"},
    # Thermal gap-pad column used for magnetics mounted on a pad to the
    # baseplate. Effective through-column k chosen so the column resistance
    # (over the PCB thickness) matches a ~1 mm gap pad at k~3 over the footprint
    # -> k_eff ~ 5 W/m.K. [ASSUMED -- refine with the real pad spec/thickness.]
    "pad":   {"k": 5.0,    "desc": "Thermal gap-pad, magnetic-to-baseplate"},
}

# Thermal-via model: effective through-plane conductivity of a filled-via
# array under a device pad, k_via = f*k_cu + (1-f)*k_fr4 (parallel paths).
K_CU = 385.0                 # W/m.K, via copper  [DOC]
VIA_FILL_FRACTION = 0.25     # [ASSUMED] fraction of pad area filled with vias
K_VIA = VIA_FILL_FRACTION * K_CU + (1 - VIA_FILL_FRACTION) * MATERIALS["fr4"]["k"]
MATERIALS["via"]["k"] = K_VIA

# Device thermal coupling. True = power devices sit over a thermal-via array
# down to the baseplate (realistic 2SF design, doc calls this acceptable
# subsea). False = top-mount through bulk FR-4 only (pessimistic worst case
# that reproduces the spreading-resistance loophole).
VIA_COUPLED = True


# ----------------------------------------------------------------------
# Geometry of the simplified (parametric) stack, in metres.
# The real run imports a STEP file; these dimensions define the fallback
# geometry and also the coordinate boxes used to tag regions.
# Stack is built along +y (through-thickness); board spans x (length) and z (width).
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Geometry:
    board_len: float = 0.300       # x  [DOC] 300 mm board
    board_wid: float = 0.100       # z  [DOC] 100 mm board

    pcb_t: float = 0.00161         # y  [2D] FR-4 stack thickness
    base_t: float = 0.008          # y  [2D] aluminium baseplate
    tim_t: float = 0.00025         # y  [2D] TIM
    wall_t: float = 0.010          # y  [2D] SS316L housing wall

    gas_h: float = 0.020           # y  [ASSUMED] internal gas head-space above PCB
    comp_h: float = 0.005          # y  [ASSUMED] generic component block height

    @property
    def y_pcb_top(self) -> float:
        return self.pcb_t

    @property
    def y_base_top(self) -> float:
        return self.pcb_t + self.base_t

    @property
    def y_tim_top(self) -> float:
        return self.pcb_t + self.base_t + self.tim_t

    @property
    def y_wall_top(self) -> float:
        return self.pcb_t + self.base_t + self.tim_t + self.wall_t


GEOM = Geometry()


# ======================================================================
# POWER MAP — the WHOLE power chain is modelled (not just the DC/DC).
# ======================================================================
# Per-stage losses come from the markdown's revised cascade analysis. The
# early 46.8 W figure was superseded: because efficiencies cascade
# (92% x 92% x 85%), each upstream stage carries more power, so the real
# worst corner (305/850 Vac, 75% system efficiency) is ~119.6 W.  [DOC]
#
# To switch operating point, change OPERATING_POINT below. To adapt to a
# different converter, edit STAGE_LOSSES (stage totals) and _DEVICES
# (which devices exist, their share of the stage, and their placement).
STAGE_LOSSES = {                                                  # [DOC]
    # stage:        buck   boost_pfc  dcdc_2sf  flyback     total
    "worst_75pct": {"buck": 33.4, "boost_pfc": 30.7, "dcdc_2sf": 52.9, "flyback": 2.6},  # 119.6 W
    "best_92pct":  {"buck": 30.8, "boost_pfc": 28.4, "dcdc_2sf": 26.1, "flyback": 2.6},  #  87.9 W
}
OPERATING_POINT = "worst_75pct"     # <-- edit to pick the scenario to solve


@dataclass(frozen=True)
class Source:
    name: str
    loss_w: float
    x_center: float        # m, along board length
    x_len: float           # m, footprint length
    z_center: float        # m, across board width
    z_len: float           # m, footprint width
    # Cooling path (BOTH conduct to the baseplate -> external coolant; the
    # interior is dry N2, a poor heat path, so nothing is gas-cooled):
    #   "conduction" = thermal-via column to the baseplate (power semiconductors).
    #   "pad"        = thermal gap-pad to the baseplate (power magnetics: the
    #                  inductors/transformer are mounted on a pad to the rail,
    #                  NOT relying on the N2 gas). Softer interface than vias.
    cooling: str = "conduction"
    note: str = ""


# Magnetics are mounted on a thermal pad to the baseplate/rail (user-confirmed),
# not via a copper-via array and not gas-cooled (dry N2 cannot carry their loss).
# They get a pad-conductivity column instead of vias. [ASSUMED classification.]
PAD_COUPLED = {"buck_inductor", "pfc_inductor", "dcdc_transformer", "flyback_aux"}


# Device breakdown within each stage. `frac` = share of that stage's loss;
# fractions within a stage sum to 1.0. Stage totals are [DOC]; the splits and
# the x/z placements are [ASSUMED] placeholders until the STEP fixes them.
# Columns: name, stage, frac, x_center, x_len, z_center, z_len  (metres)
_DEVICES = [
    ("buck_sic_mosfet",  "buck",      0.55, 0.045, 0.016, 0.050, 0.016),
    ("buck_diode",       "buck",      0.25, 0.072, 0.012, 0.050, 0.012),
    ("buck_inductor",    "buck",      0.20, 0.100, 0.024, 0.050, 0.024),
    ("pfc_mosfet",       "boost_pfc", 0.45, 0.130, 0.014, 0.050, 0.014),
    ("pfc_diode",        "boost_pfc", 0.30, 0.155, 0.012, 0.050, 0.012),
    ("pfc_inductor",     "boost_pfc", 0.25, 0.180, 0.024, 0.050, 0.024),
    ("flyback_aux",      "flyback",   1.00, 0.165, 0.014, 0.018, 0.014),
    ("dcdc_primary",     "dcdc_2sf",  0.35, 0.210, 0.024, 0.050, 0.018),
    ("dcdc_sr",          "dcdc_2sf",  0.30, 0.240, 0.024, 0.050, 0.018),
    # z_center moved 0.060 -> 0.078 so this footprint no longer overlaps
    # dcdc_sr (z 0.041-0.059). The overlap made a degenerate sliver that
    # spiked to ~940 C. [ASSUMED placement] -- keep footprints disjoint.
    ("dcdc_transformer", "dcdc_2sf",  0.20, 0.265, 0.030, 0.078, 0.030),
    ("dcdc_output",      "dcdc_2sf",  0.15, 0.290, 0.016, 0.050, 0.016),
]


def _build_power_map(operating_point: str = OPERATING_POINT):
    losses = STAGE_LOSSES[operating_point]
    return [Source(name, losses[stage] * frac, xc, xl, zc, zl,
                   cooling=("pad" if name in PAD_COUPLED else "conduction"),
                   note=f"{stage} x{frac:.0%} [ASSUMED split]")
            for name, stage, frac, xc, xl, zc, zl in _DEVICES]


POWER_MAP_2SF = _build_power_map()


def power_total() -> float:
    return sum(s.loss_w for s in POWER_MAP_2SF)


# ----------------------------------------------------------------------
# Operating-environment boundary conditions (convective Robin BC on the
# external housing surface).  [DOC]
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Case:
    name: str
    h: float            # W/m^2.K external convection coefficient
    t_inf_c: float      # C EXTERNAL coolant/ambient (sea or surface air)
    desc: str
    # Internal sealed-N2 temperature (spec ~85 C). NOT a heat sink: dry N2 is a
    # poor path, so magnetics are conduction-cooled (thermal pad to baseplate),
    # not gas-cooled. Kept only as the radiation environment / ambient for tiny
    # un-sunk parts (e.g. control ICs). [DOC/spec]
    t_internal_c: float = 85.0


CASES = {
    "subsea":  Case("subsea",  100.0, 20.0, "Oil-coupled subsea, continuous primary case", t_internal_c=85.0),  # [DOC]
    # External commissioning AIR is 50 C (doc Section 4). The 85 C figure is the
    # INTERNAL sealed-N2 temperature, not the external convection ambient.
    "surface": Case("surface",   8.0, 50.0, "Still-air surface commissioning (50 C external air), derated/limited", t_internal_c=85.0),  # [DOC]
}


# ----------------------------------------------------------------------
# Housing rejection area.
# Heat ultimately leaves over the whole cylindrical housing, not just the
# baseplate footprint. Treating the housing as a near-isothermal extended
# surface (steel, large area, low housing-to-fluid R per the study), the
# convective face in the model sees an effective coefficient
#     h_eff = h * A_housing / A_face .
# This is what makes the surface case physical: with the footprint area only,
# 119.6 W in still air gives an impossible ~600 C; with the true area it gives
# ~165 C (a real fail needing fins/forced air, matching the study's ~52 W
# still-air rejection figure).  [DOC]  Set USE_HOUSING_AREA=False to revert.
import math

HOUSING_D = 0.125          # m, housing outer diameter  [DOC]
HOUSING_L = 0.414          # m, housing length          [DOC]
A_HOUSING = math.pi * HOUSING_D * HOUSING_L + 2 * math.pi * HOUSING_D**2 / 4
USE_HOUSING_AREA = True
P_OUT = 300.0              # W, converter output power (for efficiency sweeps)


def effective_h(case: "Case") -> float:
    """Convection coefficient seen by the meshed baseplate face."""
    if not USE_HOUSING_AREA:
        return case.h
    a_face = GEOM.board_len * GEOM.board_wid
    return case.h * A_HOUSING / a_face


# Design limits  [DOC]
T_J_MAX_C = 125.0
T_AMBIENT_MAX_C = 85.0


def c_to_k(t_c: float) -> float:
    return t_c + 273.15
