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

## 4. Assign materials (conductivity is all that matters here)

For each of the four materials, **Model → Material → Material for solid**, then in
the task panel set **Thermal conductivity** and pick the solids under
*References*:

| Material | k (W/m·K) | Assign to |
|----------|-----------|-----------|
| FR-4 (PCB) | 0.30 | the PCB layer **and** all device boxes (the catch-all) |
| Aluminium  | 160  | the baseplate layer |
| TIM        | 3.0  | the TIM layer |
| SS316L     | 16   | the housing-wall layer |

> ⚠️ **Catch-all rule.** Leave exactly **one** material with an **empty
> References list** — FreeCAD assigns every otherwise-unclaimed element to it.
> Make **FR-4** the catch-all (empty references) and reference the three clean
> single-solid layers explicitly. Otherwise you get *"no material assigned"*.
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
- **Ambient temperature →** 20 °C subsea, 85 °C surface.

All faces with no constraint are treated as adiabatic (zero flux), so heat can
only leave through this face.

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
  (≈ 29 °C subsea, ≈ 168 °C surface). If they don't, the BC or mesh is wrong.
- Each device's peak is its junction temperature *in this model* (loss injected
  into the FR-4 layer).

---

## 10. Export to ParaView (optional, nicer visuals + the margin table)

CalculiX writes `Mesh.frd` in the solver's working directory. Hand it to the
`sim3d_paraview` pipeline:

```bash
ccx2paraview Mesh.frd vtu     # -> Mesh.vtu, openable in ParaView
```

or just run `python run_pipeline.py --from convert` after copying the `.frd` to
`results/<case>.frd`. That gives the cut-away render, the over-limit isosurface,
the `.pvsm` state, and the per-device margin CSV.

---

## Modelling caveats (so you read the numbers correctly)

- **No thermal-via coupling.** Device losses go into bare FR-4 (k = 0.3), so the
  through-plane resistance is huge and absolute junction temperatures are
  pessimistic — the subsea FEM shows MOSFETs ~270 °C while the via-coupled hand
  calc / SfePy model give ~40–75 °C. To make the numbers real, model the via
  array under each device (a high-k column through the PCB) or bottom-mount the
  device to the baseplate. This is a **geometry** change in step 1.
- **One junction limit (125 °C) for all parts.** Real limits differ (SiC ~175 °C,
  magnetics/electrolytics lower).
- **Single convective face with area scaling**, not a true conjugate housing
  mesh. Good for a first-order rejection check; a full cylindrical housing needs
  the STEP geometry.
