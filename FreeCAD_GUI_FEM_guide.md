# Building the SEM 300 W thermal model in the FreeCAD GUI (FEM workbench)

This is the manual, click-by-click version of what `sim3d/freecad_thermal.py`
does headlessly. It reproduces the steady-state conduction model of the layered
stack (PCB → aluminium baseplate → TIM → SS316 housing) with per-device heat
sources and a convective boundary, solved by CalculiX, and viewed in ParaView.

Workflow split (matches your preference): **geometry is built in Python**, then
**all the FEM setup is done in the GUI**. Tested mental model is FreeCAD 1.1.x;
menu labels move slightly between versions, so each step notes where to look.

References: FreeCAD wiki *FEM CalculiX*, *FEM Heat* / *Constraint heat flux*, and
*FEM MeshGmsh*.

---

## 0. Prerequisites

- FreeCAD 1.1.x (bundles the CalculiX `ccx` solver and the Gmsh mesher).
- The project's `sim3d/config.py` (single source of truth for dimensions,
  materials, the device power map and boundary conditions).
- For viewing the result outside FreeCAD: ParaView + `ccx2paraview` (see the
  `sim3d_paraview` pipeline).

---

## 1. Geometry in Python (you almost always do this)

You can paste geometry-building code straight into FreeCAD's Python console
(**View → Panels → Python console**). Two non-negotiable rules learned the hard
way:

1. **Build the layers and the per-device boxes, then boolean-fragment them into
   ONE compound, and consolidate that into a single `Part::Feature` (call it
   `Stack`).** A node-matched FEM mesh across material interfaces requires the
   blocks to share faces — that is what `BOPTools.SplitFeatures.makeBooleanFragments`
   gives you.
2. **The mesh object and every material / load reference must point at that same
   `Stack` object.** If the mesh is built on one object and a material references
   another, the solid sub-names resolve against the wrong shape and CalculiX
   reports *"no material assigned"* on those elements.

The easiest path is to reuse the project function rather than retype it. In the
Python console:

```python
import sys; sys.path.append("/full/path/to/ThermalDesign_300W/sim3d")
import FreeCAD as App
doc = App.newDocument("sem_manual")
import freecad_thermal as ft
geo, classify = ft.build_geometry(doc)   # builds the consolidated "Stack"
doc.recompute()
import FreeCADGui as Gui; Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
```

You now have a `Stack` solid in the tree with 4 layer regions plus one small
solid per device inside the PCB. Switch the workbench dropdown to **FEM**.

> ⚠️ **Footprint overlaps.** If two device boxes overlap (this project had
> `dcdc_sr` ↔ `dcdc_transformer` colliding), the boolean fragment splits them
> into a shared solid and a per-device heat source can be silently lost. The
> updated `freecad_thermal.py` warns on overlap and attributes every footprint
> robustly, but when placing devices by hand keep footprints disjoint.

---

## 2. Create the Analysis container

Select the `Stack` in the tree, then **Model → Analysis container** (toolbar:
the flask icon). This makes an `Analysis` group; everything below goes inside it.
Most versions also drop a default CalculiX solver in — if not, add it next.

---

## 3. Add and configure the CalculiX solver (this makes it a *thermal* solve)

If there is no solver, **Solve → CalculiX Standard** (or *Solver CalculiX ccxtools*).
Double-click the solver to open its task panel and set:

- **Analysis type → Thermomechanical**
- **Thermo mech type → Pure heat transfer**
- **Steady state → ticked**

That trio is what makes CalculiX write `*HEAT TRANSFER, STEADY STATE` (pure
conduction, no mechanics). Leave geometric nonlinearity *linear*.

---

## 4. Assign materials, including the thermal vias

For each material, **Model → Material → Material for solid**, then in the task
panel set **Thermal conductivity** and pick the solids under *References*:

| Material | k (W/m·K) | Assign to |
|----------|-----------|-----------|
| FR-4 (PCB) | 0.30 | PCB remainder — **leave References EMPTY (catch-all)** |
| **Via array** | **≈ 96.5** (`config.K_VIA`) | the **power-semiconductor** columns (conduction-cooled parts) |
| **Thermal gap-pad** | **≈ 5** (`MATERIALS["pad"]`) | the **magnetic** columns (inductors, transformer, flyback — pad-mounted to baseplate) |
| Aluminium  | 160  | the baseplate layer |
| TIM        | 3.0  | the TIM layer |
| SS316L     | 16   | the housing-wall layer |

> 🔑 **The vias are what make the design realistic.** Each device's column
> through the PCB is given the **via-array effective conductivity**, not bare
> FR-4. The effective value is `k_via = f·k_cu + (1−f)·k_fr4` with copper
> `k_cu = 385` and via-area fill fraction `f = 0.25` → **≈ 96.5 W/m·K**
> (`config.K_VIA`, `config.VIA_FILL_FRACTION`). Without this the device columns
> are k = 0.3 and junctions read hundreds of °C; with it, subsea devices drop to
> ~30–34 °C. In the headless script this is automatic
> (`config.VIA_COUPLED = True`); in the GUI you make it real by assigning the
> device solids to the **Via array** material instead of FR-4. For the
> pessimistic top-mount-through-FR-4 worst case, just leave the device columns on
> FR-4 (or set `VIA_COUPLED = False`).

> ⚠️ **Catch-all rule.** Leave exactly **one** material with an **empty
> References list** — FreeCAD assigns every otherwise-unclaimed element to it.
> Make **FR-4** the catch-all (empty references); reference Via array, Aluminium,
> TIM and SS316L explicitly. Otherwise you get *"no material assigned"*.
> The elastic/specific-heat fields are ignored by a steady-state conduction
> solve; only conductivity is used.

---

## 5. Add a body heat source per device

For each device: select its solid in the 3-D view, then **Model → Mechanical/
thermal constraints → Body heat source** (thermal). In the task panel:

- **Mode → Total Power**
- **Total power →** the device's loss in watts (from `config.POWER_MAP_2SF`,
  e.g. buck SiC MOSFET = 18.37 W).
- Confirm the device solid is in *References*.

"Total Power" lets CalculiX convert watts to a volumetric body flux
(`*DFLUX … BF`) over that solid — you don't hand-compute W/m³. Add one source
per device; the sum across all devices must equal the total loss (119.6 W at the
worst corner). If a device shares a split footprint, reference **all** of its
sub-solids in the one source.

---

## 6. Add the convective boundary condition

Select the **outer housing face** (top of the stack), then **Model → … →
Constraint heat flux**, and in the task panel set:

- **Type → Convection**
- **Film coefficient →** the effective coefficient. The model applies convection
  on this one face but scales it to the *whole housing area*:
  `h_eff = h · A_housing / A_face`. For subsea (`h=100`) that is ≈ 624 W/m²·K;
  for surface still-air (`h=8`) ≈ 49.9 W/m²·K. (`config.effective_h(case)`.)
- **Ambient temperature →** 20 °C subsea, **50 °C surface** (the external
  commissioning *air*; the 85 °C figure is the internal sealed-gas temperature,
  not the external convection ambient).

All faces with no constraint are treated as adiabatic (zero flux), so heat can
only leave through this face. This single-face area-scaling is a stand-in for the
real cylindrical housing — see "Setting up with a STEP file" to replace it with
true geometry.

> 🔁 **Two conduction paths (interior is dry N₂ — a poor heat path, so nothing
> is gas-cooled).** Power semiconductors use a **via column** (`Via array`
> material, step 4). **Magnetics** (inductors, transformer, flyback —
> `config.PAD_COUPLED`) are mounted on a **thermal gap-pad to the baseplate**, so
> give their columns the **`Thermal gap-pad` material** (`MATERIALS["pad"]` ≈
> 5 W/m·K) instead of the via array. No extra convection constraint — they
> conduct to the cool baseplate like the semis, just through a softer interface.
> (Dry N₂ cannot cool a multi-watt magnetic; every magnetic needs this pad or an
> equivalent clamp to the rail.)

---

## 7. Add the initial temperature

**Model → … → Initial temperature**, set it to the ambient of the case. For a
steady-state solve this is only the solver's starting guess, but CalculiX
requires it for a thermal step.

> ⚠️ **Version trap.** FreeCAD 1.0 names this property `initialTemperature`
> (lowercase); newer branches use `InitialTemperature`. If you script it, set
> whichever your build exposes. All temperatures in FreeCAD properties are in
> **Kelvin** — the solver returns Kelvin and you shift to °C only for display.

---

## 8. Mesh with Gmsh (where accuracy is won or lost)

Select `Stack`, then **Mesh → FEM mesh from shape by Gmsh**. In the task panel:

- **Max element size →** small enough to put several elements **through the
  1.61 mm PCB thickness**, which is the dominant resistance. A global 6 mm (the
  old default) is *larger than the PCB is thick* and badly under-resolves the
  through-plane gradient. Use **≈ 1.0–1.5 mm**, or set a local **Gmsh mesh region**
  refinement of ~0.5 mm on the PCB/device solids and keep the housing coarse.
- **Second order → ticked** (quadratic `C3D10` tets). Linear `C3D4` tets are
  stiff and smear thermal gradients; second order is far more accurate for the
  same node budget.

Click **Apply**, then check the element count and that the PCB layer has through-
thickness elements.

---

## 9. Solve and view the temperature field

Double-click the solver → **Write .inp file** → **Run CalculiX**. When it
finishes, a result object appears. Double-click it, set the field to
**Temperature**, and the stack colours by temperature (Kelvin — subtract 273.15
mentally, or use the ParaView pipeline for a °C scale). Inspect:

- The coolest conductive nodes should sit near the baseplate temperature you can
  predict by hand: `T_base = T_amb + P_total · R_external`
  (≈ 29 °C subsea, ≈ 133 °C surface at 50 °C air). If they don't, the BC or mesh
  is wrong.
- Each device's peak is its junction temperature *in this model* (loss injected
  into its column; with the via material that column is high-k, so the device
  sits only ~1–2 °C above the baseplate). Expect subsea ~30–34 °C (PASS) and
  surface ~132–140 °C (over the 125 °C limit → derate).

---

## 10. View and post-process in ParaView

CalculiX writes `Mesh.frd` in the solver working directory. Convert it, then set
up the scene. The automated pipeline does all of this for you
(`python run_pipeline.py` → `results/<case>.png/.pvsm/.csv/_board_map.png`), but
to drive ParaView by hand:

**Convert**
```bash
ccx2paraview Mesh.frd vtu      # -> Mesh.vtu  (nodal temp = NT [K], heat flux = FLUX)
```

**Open and colour**
1. **File → Open** → the `.vtu` → **Apply**.
2. Colour dropdown → **NT** (Kelvin). For °C, add **Filters → Common → Calculator**,
   Attribute *Point Data*, expression `NT - 273.15`, name it `Temperature_C`, Apply,
   and colour by that.
3. **Edit Color Map** → **Rescale to Custom Range** → **50 to 125** so blue = cool
   margin and red = at the junction limit. Pick the **Turbo** preset.

**See inside (the hot spots are buried in the stack)**
4. **Filters → Common → Clip**, Plane type, leave it through the centre, Apply — a
   cut-away cross-section showing the internal gradient.
5. **Filters → Common → Contour** on `Temperature_C` at **125** → the red
   over-limit isosurface (the at-risk volume at a glance).

**See the heat flow**
6. **Filters → Common → Glyph**, Glyph Type *Arrow*, Orientation Array **FLUX**,
   Scale Array **FLUX**, Scale Factor a few mm, Glyph Mode *Every Nth Point* →
   arrows showing where and how strongly heat flows toward the housing face.

**Quantify**
7. **Filters → Data Analysis → Plot Over Line**, draw it vertically through a hot
   device, Apply — the T profile across PCB → Al → TIM → housing shows *which*
   interface eats the ΔT.
8. Hover-points / **Find Data** reads any node's exact temperature.

**Reuse**: the pipeline saves a `.pvsm` per case — **File → Load State →
`results/<case>.pvsm`** restores the whole scene (clip, colormap, isosurface,
housing cylinder, flux glyphs) instantly. The grey see-through cylinder in that
scene is the **visual housing reference only** — it is not simulated.

---

## 11. Setting up with a STEP file (real geometry + real housing)

The steps above use the parametric block stack. To solve real CAD — and to turn
the housing into actual solved geometry instead of the area-scaled boundary
condition — swap only the geometry; steps 2–10 are unchanged.

1. **Import the STEP.** **File → Import** → your `.step` (or in the Python
   console `import Import; Import.insert("/path/sem.step", doc.Name)`). You get
   one solid per body (PCB, baseplate, devices, housing, …).
2. **Make one conformal solid.** Select all imported solids → **Part workbench →
   Boolean → Boolean Fragments** (or `BOPTools`), then consolidate into a single
   `Part::Feature` named `Stack`. The mesh and *every* material/load reference
   must point at this one object (same rule as step 1).
3. **Materials (step 4) by picking solids.** Now you select the *real* bodies:
   assign Aluminium to the baseplate/rail, SS316L to the **housing**, the Via
   array to the device columns, etc., FR-4 as the empty-reference catch-all.
4. **Heat sources (step 5)** on the real device bodies, Total Power = each loss.
5. **Convection on the REAL housing faces (step 6), and drop the area trick.**
   Select the housing's outer cylindrical faces for the **Constraint heat flux →
   Convection**, and use the *true* coefficient `case.h` (subsea 100, surface 8)
   — **not** the scaled `effective_h`. In `config.py` set
   `USE_HOUSING_AREA = False`; the scaling only existed to fake the housing area
   that you now have as real geometry.
6. **Mesh (step 8).** Keep elements small through the thin PCB/TIM layers
   (local refinement) and coarser in the bulk housing; second order on.
7. **Solve and view (steps 9–10)** exactly as before — now the housing shows its
   own temperature field and the board→rail→housing→fluid conjugate path is real.

> The STEP file never leaves your machine — the whole toolchain runs locally.

---

## Modelling caveats (so you read the numbers correctly)

- **Via fill fraction is assumed.** The via material uses `f = 0.25` area fill
  (`config.VIA_FILL_FRACTION`) → k ≈ 96.5 W/m·K. This is what gives the realistic
  ~30 °C subsea junctions; set `VIA_COUPLED = False` (device columns on FR-4) for
  the pessimistic worst case, and adjust `f` to your real array.
- **One junction limit (125 °C) for all parts.** Real limits differ (SiC ~175 °C,
  magnetics/electrolytics lower) — edit per part.
- **Housing is an area-scaled boundary condition, not geometry** (until you do
  step 11). Good for a first-order rejection check; the surface-case housing
  temperature is only first-order until the STEP/conjugate model is built.
- **No contact resistances** (die-attach, board-to-rail, TIM contact beyond the
  bulk layer). Real interfaces add resistance, so true temperatures run a bit
  higher than this model.
