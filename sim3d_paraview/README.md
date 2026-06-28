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
| `<case>.png` | rendered temperature field (Celsius), cut-away + over-temp isosurface + housing cylinder + flux glyphs |
| `<case>.pvsm` | **ParaView state** — open in the GUI for the ready-made scene to rotate / slice / probe / plot-over-line |
| `<case>_margins.csv` | **per-device junction-temperature margin table** (one CSV per case) |
| `<case>_board_map.png` | **labeled board map** — every device tagged name / loss / peak temp, coloured by temperature |

`<case>` is `subsea` and `surface`, the two operating environments in
`../sim3d/config.py`. The report stage of `run_pipeline.py` regenerates the two
margin CSVs and two board maps automatically for both cases.

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

`render_paraview.py` has settings at the top of the file:

- `USE_CLIP` (default `True`) — the device heat sources sit *inside* the stack,
  so the outer surface reads near-ambient and hides the gradient. The clip cuts
  the model through its centre to expose the interior cross-section where the
  peak temperature lives. Set `False` for a plain exterior render.
- `CLIP_NORMAL` — the cut-plane normal in mesh axes (`x` = board length,
  `y` = through-thickness, `z` = board width). The default `[0,0,1]` takes a
  lengthwise vertical section through the PCB heat-injection layer.
- `SHOW_ISOSURFACE` — red surface at the 125 °C limit (the at-risk boundary).
- `SHOW_HOUSING` — see-through Ø125 × 414 mm cylinder around the board as a
  spatial reference. **It is NOT simulated** (carries no temperature); it just
  shows where the real housing sits. See "The cylindrical housing" below.
- `SHOW_FLUX_GLYPHS` — arrows of the CalculiX `FLUX` field; arrow length is
  scaled to heat-flux magnitude (auto-fit per case), so you can see where and
  how strongly heat flows. `GLYPH_STRIDE` controls arrow density.

Temperatures are shifted Kelvin → Celsius for display only; the solver field is
untouched. The temperature array is auto-detected (`NT`), so the render still
works if a future CalculiX/ccx2paraview version renames it.

## The cylindrical housing (important)

Right now the housing is **not real geometry in the simulation**. The FEM model
is the flat PCB stack (PCB → Al → TIM → SS plate). The Ø125 × 414 mm cylindrical
housing from the design doc is represented only as a **scaled convection
coefficient** on the top face: `effective_h = h · A_housing / A_face`
(`config.effective_h`). This reproduces the housing's *heat-rejection area*
correctly for a first-order check, but there is no housing-shaped body, so it has
no temperature field and no internal-to-housing gradient.

The cylinder you see in the ParaView render (`SHOW_HOUSING`) is a **visual
reference only** — it shows where the housing sits relative to the board; it is
not meshed or solved.

To make the housing **real, solved geometry** (with its own temperature field and
a true conjugate path board → gas/rail → housing → fluid), use the STEP path
below. Once a STEP enclosure is imported and meshed, drop the `effective_h`
area-scaling (set `USE_HOUSING_AREA = False` in `config.py`) and apply the real
convection coefficient `case.h` directly on the actual housing outer faces —
the scaling trick is only a stand-in for the missing geometry.

## Swapping in a STEP file (parametric stack → real CAD + real housing)

The pipeline currently runs the **parametric layered stack** defined in
`../sim3d/config.py`. To drive it from real CAD (and get the real housing),
change only the geometry source in `../sim3d/freecad_thermal.py`; the mesh,
solve, and the whole `sim3d_paraview` tail stay the same.

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

The model now includes **thermal-via coupling** (`config.VIA_COUPLED = True`):
each device's through-PCB column uses the via-array effective conductivity
(`config.K_VIA` ≈ 96 W/m·K) instead of bare FR-4. This is the realistic
bottom-cooled design, and it gives **subsea: all devices PASS (~30–34 °C)** and
**surface (50 °C air): all FAIL by 7–15 °C at full power → derate to ~270 W**.
Still keep in mind:

- Set `VIA_COUPLED = False` in `config.py` for the pessimistic
  top-mount-through-FR-4 worst case (devices jump to hundreds of °C). The via
  fill fraction (`VIA_FILL_FRACTION = 0.25`) is an `[ASSUMED]` value — adjust to
  your real via array.
- One junction limit (125 °C) is applied to every device. Real limits differ
  (SiC ~175 °C, magnetics/electrolytics often lower) — edit `LIMITS` in
  `device_report.py` for per-part ratings.
- The housing is a boundary-condition approximation, not solved geometry — see
  "The cylindrical housing" above. The absolute surface-case housing temperature
  is only first-order until the STEP/conjugate model is built.

So the *relative* ranking (which devices and which case are worst) is
informative; the *absolute* pass/fail is not, until via-coupling is added to the
FreeCAD geometry. That is a modelling change in `freecad_thermal.py`, separate
from this visualization layer.
