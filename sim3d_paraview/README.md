# sim3d_paraview — Antmicro-style thermal visualization tail

This sub-project reproduces the open-source thermal workflow from Antmicro's
[blog post](https://antmicro.com/blog/2025/03/open-source-thermal-simulation-analysis-and-visualization)
for the SEM 300 W module: **FreeCAD + CalculiX → ccx2paraview → ParaView**.

It adds **no physics**. It reuses the existing solver in `../sim3d`
(`freecad_thermal.py` and `config.py`) unchanged — Python only builds geometry
and inputs; FreeCAD meshes and CalculiX solves the steady-state conduction
problem — and bolts on the visualization tail that converts the CalculiX results
to VTU and renders them in ParaView.

## Prerequisites

| Tool | Used by | Install |
|------|---------|---------|
| FreeCAD 1.x (provides `freecadcmd` + bundled CalculiX `ccx`) | stage 1 | https://www.freecad.org |
| `ccx2paraview` (in your project venv) | stage 2 | `pip install 'ccx2paraview[VTK]'` |
| ParaView (provides `pvpython`) | stage 3 | https://www.paraview.org/download |

The scripts find `freecadcmd` and `pvpython` automatically in `/Applications`.
Override either with an environment variable if it lives elsewhere:

```bash
export FREECADCMD="/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
export PVPYTHON="/Applications/ParaView-6.0.app/Contents/bin/pvpython"
```

## Run

One command runs all three stages, routing each to the correct interpreter:

```bash
python run_pipeline.py
```

Resume from a later stage (e.g. after editing only the render settings):

```bash
python run_pipeline.py --from convert   # .frd -> .vtu, then render
python run_pipeline.py --from render    # re-render existing .vtu only
```

Or run the stages by hand (note each needs a *different* interpreter):

```bash
"$FREECADCMD" solve_cases.py     # 1. solve both cases  -> results/<case>.frd
python frd_to_vtu.py             # 2. convert            -> results/<case>.vtu
"$PVPYTHON" render_paraview.py   # 3. render + state     -> results/<case>.png/.pvsm
python device_report.py          # 4. margin table       -> results/device_margins.csv
```

## Outputs (in `results/`)

| File | Contents |
|------|----------|
| `<case>.frd` | raw CalculiX result (nodal temperature `NT`, heat flux `FLUX`) |
| `<case>.vtu` | same field as VTU, openable directly in the ParaView GUI |
| `<case>.png` | rendered temperature field (Celsius), cut-away + over-temp isosurface + scalar bar |
| `<case>.pvsm` | **ParaView state** — open in the GUI for the ready-made scene to rotate / slice / probe / plot-over-line |
| `device_margins.csv` | **per-device junction-temperature margin table** (both cases) |

`<case>` is `subsea` and `surface`, the two operating environments in
`../sim3d/config.py`.

### The engineering result: `device_margins.csv`

The peak field number is not the deliverable — this table is. For every device
it gives its loss, the peak temperature inside its footprint (its junction
temperature in this model, where the loss is injected), the rise over ambient,
the margin to the limit (`config.T_J_MAX_C`, 125 °C), and PASS/FAIL. Open the
`.pvsm` alongside it to see *where* the failing devices are.

To open the interactive scene: ParaView GUI → File → Load State → `<case>.pvsm`.
Useful probes once loaded: **Plot Over Line** through the stack (PCB → Al → TIM →
housing) to see which interface eats the ΔT; **Threshold** on `Temperature_C` to
isolate the over-limit region.

## Notes on the render

`render_paraview.py` has two settings at the top of the file:

- `USE_CLIP` (default `True`) — the device heat sources sit *inside* the stack,
  so the outer surface reads near-ambient and hides the gradient. The clip cuts
  the model through its centre to expose the interior cross-section where the
  peak temperature lives. Set `False` for a plain exterior render.
- `CLIP_NORMAL` — the cut-plane normal in mesh axes (`x` = board length,
  `y` = through-thickness, `z` = board width). The default `[0,0,1]` takes a
  lengthwise vertical section through the PCB heat-injection layer.

Temperatures are shifted Kelvin → Celsius for display only; the solver field is
untouched. The temperature array is auto-detected (`NT`), so the render still
works if a future CalculiX/ccx2paraview version renames it.

## Swapping in a STEP file (parametric stack → real CAD)

The pipeline currently runs the **parametric layered stack** defined in
`../sim3d/config.py`. To drive it from real CAD instead, change only the
geometry source in `../sim3d/freecad_thermal.py`; the mesh, solve, and the whole
`sim3d_paraview` tail stay the same.

1. **Import the STEP in `build_geometry()`.** Replace the `Part::Box`
   construction with a STEP import, e.g.

   ```python
   import Import
   Import.insert("/path/to/sem_module.step", doc.Name)
   solids = [o for o in doc.Objects if getattr(o, "Shape", None)
             and o.Shape.Solids]
   ```

   Consolidate the imported solids into the single `Part::Feature` named
   `Stack` that the mesh and every material/load reference use (the existing
   "same object for mesh and references" rule still applies — see the
   `freecad-calculix-interface` note).

2. **Map each solid to a material in `classify()`.** Replace the
   centre-of-mass/layer test with a mapping from each STEP solid (by name,
   label, or bounding box) to a `MATERIALS` key, and to a device `Source` for
   the solids that carry a loss. Keep exactly **one** material with empty
   `References` as the catch-all (currently `fr4`), or CalculiX errors with
   "no material assigned".

3. **Point the convection BC at the real housing face.**
   `_outer_face_names()` currently finds the single planar top face of the
   parametric stack. For a real enclosure, select the outer housing face(s) by
   name or by an outward-normal/area test, and feed `effective_h(case)` (or the
   per-face film coefficient you want) to the `Convection` constraint.

4. Run `python run_pipeline.py` as usual. Everything downstream is unchanged.

> The STEP file never leaves your machine — the entire toolchain runs locally.

## Caveat on the numbers (read before trusting the verdicts)

The margins are correct **for the current model**, but the model under-represents
the heat path, so treat the absolute temperatures as pessimistic, not as the
real design verdict:

- `freecad_thermal` injects each device's loss into the **FR-4 PCB layer with no
  thermal-via coupling to the baseplate** (k_FR4 ≈ 0.3 W/m·K). The real 2SF
  design bottom-cools the power devices through a via array / direct path. With
  that resistance missing, ΔT is hugely inflated — which is why even the subsea
  case shows MOSFETs at ~270 °C here, while the **via-coupled SfePy model in
  `../sim3d` gives subsea T_case ≈ 43–76 °C (PASS)** for the same power.
- One junction limit (125 °C) is applied to every device. Real limits differ
  (SiC ~175 °C, magnetics/electrolytics often lower) — edit `LIMITS` in
  `device_report.py` for per-part ratings.

So the *relative* ranking (which devices and which case are worst) is
informative; the *absolute* pass/fail is not, until via-coupling is added to the
FreeCAD geometry. That is a modelling change in `freecad_thermal.py`, separate
from this visualization layer.
