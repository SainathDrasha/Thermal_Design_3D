# SEM 300 W — 3D Thermal Simulation Pipeline

Steady-state 3D conduction model of the sealed SEM power-converter module,
solved with open-source Python (Gmsh + SfePy + PyVista). It covers the **whole
power chain** (buck pre-stage, boost PFC, 15 W flyback aux, and the 2SF DC/DC)
and two operating environments (subsea oil-coupled and surface still-air).

It is a genuine 3D solve: a 3D hexahedral mesh (~31k elements) of the layered
block assembly, solving `div(k grad T) + q = 0` with a convective (Robin)
boundary on the housing outer face.

## Install

Python 3.10+:

```
pip install numpy scipy sfepy meshio pyvista
pip install gmsh          # only needed for the STEP-import path
```

## Run

From this folder:

```
python run_all.py          # gate -> mesh -> solve -> 3D render (one command)
```

Or stage by stage:

```
python rayleigh.py         # gas convection check: conduction-FEM vs CFD verdict
python mesh_gen.py         # build mesh -> mesh_parametric.vtk
python solve.py            # solve both cases -> result_*.vtk (+ energy balance)
python postprocess.py      # 3D images -> view_*.png
python postprocess.py --show   # interactive 3D windows
```

## Outputs

| File | Contents |
|------|----------|
| `result_subsea.vtk`, `result_surface.vtk` | 3D temperature field (open in ParaView) |
| `view_subsea.png`, `view_surface.png` | COMSOL/ANSYS-style renders with device labels |
| `mesh_parametric.vtk` | the mesh with material regions |

## How to edit / adapt

Everything is driven by **`config.py`**:

- **Operating point** — set `OPERATING_POINT` to `"worst_75pct"` (119.6 W) or
  `"best_92pct"` (87.9 W). Add your own entries to `STAGE_LOSSES`.
- **Power map** — `_DEVICES` lists every device: its stage, its share `frac`
  of that stage's loss, and its `x/z` position and footprint. Edit/add rows to
  match your board.
- **Materials** — `MATERIALS` (conductivities). Via model: `VIA_FILL_FRACTION`,
  and `VIA_COUPLED` (`True` = devices over a thermal-via array to the baseplate;
  `False` = top-mount through FR-4, the pessimistic case).
- **Geometry** — `Geometry` dataclass (layer thicknesses, board size).
- **Boundary conditions** — `CASES` (convection coefficient `h` and ambient
  `t_inf_c` per environment).

To reuse the pipeline for a different converter, edit those tables only; the
mesh, solver and visualization stages are generic.

## STEP geometry (later)

`mesh_gen.gmsh_from_step(step_path, out_vtk)` imports a STEP assembly via the
Gmsh OCC kernel and tags each solid as a physical group. Drop a STEP file in and
map its solids to materials in `solve.py` to replace the parametric blocks.

## Validation

- Solver is **energy-conservative**: wall heat-out equals injected power to
  0.00% (two-pass source normalization handles coarse-mesh footprint sampling).
- Results track the design study: worst-case (119.6 W) subsea ~76 C (within the
  125 C limit) and surface still-air far over limit — i.e. subsea is the
  continuous case, surface needs derating/fins.
- The Rayleigh gate confirms the sealed gas is conduction-dominated
  (k_eff < 0.1 W/m.K), so full CFD is not required for this design.

## Flagged assumptions

Tagged `[ASSUMED]` in `config.py`: device positions and footprints
(placeholders until the STEP), intra-stage power splits, via fill fraction
(0.25), package conductivity (20 W/m.K), and gas effective conductivity. Stage
loss totals and material/BC values are from the design study `[DOC]`.
