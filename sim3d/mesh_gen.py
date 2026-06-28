"""
Mesh generation for the SEM 300 W 3D thermal pipeline.

Two paths share one output contract (a meshio mesh written to VTK plus a
cell-wise integer "mat_id"):

  1. gmsh_from_step()  -- production path. Imports the user's STEP assembly
     through the gmsh OpenCASCADE kernel, tags each solid as a physical
     volume, and writes a tetra mesh. Requires `pip install gmsh`
     (ships wheels for macOS/Windows/x86-Linux).

  2. parametric_mesh() -- fallback path. Builds a graded structured-hex
     mesh of the simplified layered stack (PCB/Al/TIM/housing wall) using
     only numpy. Runs anywhere and lets the solver be exercised before the
     STEP file arrives. Heat sources are injected at the PCB top (same
     convention as the validated 2D model), so discrete component solids are
     not meshed here.

Material id map (shared): 1=fr4, 2=al, 3=tim, 4=ss316.
"""

import numpy as np
import meshio

from config import GEOM, POWER_MAP_2SF, VIA_COUPLED

MAT_ID = {"fr4": 1, "al": 2, "tim": 3, "ss316": 4,
          "component": 5, "gas": 6, "via": 7}


def _footprint_at(x, z):
    """Boolean mask: points lying under any device footprint."""
    inside = np.zeros(np.shape(x), dtype=bool)
    for s in POWER_MAP_2SF:
        inside |= (np.abs(x - s.x_center) <= s.x_len / 2.0) & \
                  (np.abs(z - s.z_center) <= s.z_len / 2.0)
    return inside


# ----------------------------------------------------------------------
# Production path: STEP -> tetra mesh via gmsh OCC
# ----------------------------------------------------------------------
def gmsh_from_step(step_path: str, out_vtk: str, mesh_size: float = 0.004) -> str:
    """Mesh a STEP assembly and write a tagged VTK. Returns out_vtk.

    Each solid in the STEP becomes a gmsh physical volume named by its order;
    map those names to materials in solve.py once the real assembly is known.
    """
    import gmsh  # imported lazily so the fallback path needs no gmsh

    gmsh.initialize()
    try:
        gmsh.model.add("sem")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        # One physical group per solid volume so regions survive into the mesh.
        for dim, tag in gmsh.model.getEntities(dim=3):
            gmsh.model.addPhysicalGroup(3, [tag], tag)
            gmsh.model.setPhysicalName(3, tag, f"solid_{tag}")

        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size / 5.0)
        gmsh.model.mesh.generate(3)
        gmsh.write(out_vtk)
    finally:
        gmsh.finalize()
    return out_vtk


# ----------------------------------------------------------------------
# Fallback path: graded structured-hex stack
# ----------------------------------------------------------------------
def _graded_axis(segments):
    """Concatenate per-segment linspaces into one monotone node array.

    segments: list of (length, n_div). Shared faces are de-duplicated.
    """
    nodes = [0.0]
    x0 = 0.0
    for length, ndiv in segments:
        seg = np.linspace(x0, x0 + length, ndiv + 1)[1:]
        nodes.extend(seg.tolist())
        x0 += length
    return np.array(nodes)


def parametric_mesh(nx: int = 60, nz: int = 24):
    """Build the layered block-assembly hex mesh.

    y runs from the component side (y=0, adiabatic) down to the housing outer
    face (max y, convective). Layers, top to bottom:
        component layer  -> device blocks (in footprints) + gas elsewhere
        PCB              -> thermal-via columns (in footprints, if VIA_COUPLED)
                            + FR-4 elsewhere
        baseplate (Al) / TIM / housing wall (SS316L)

    Returns (points, cells_hex, mat_id, y_layers).
    """
    g = GEOM
    # Graded so the thin TIM and PCB are resolved.
    y_nodes = _graded_axis([
        (g.comp_h, 3),
        (g.pcb_t,  3),
        (g.base_t, 8),
        (g.tim_t,  2),
        (g.wall_t, 6),
    ])
    x_nodes = np.linspace(0.0, g.board_len, nx + 1)
    z_nodes = np.linspace(0.0, g.board_wid, nz + 1)

    X, Y, Z = np.meshgrid(x_nodes, y_nodes, z_nodes, indexing="ij")
    points = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])

    nxp, nyp, nzp = len(x_nodes), len(y_nodes), len(z_nodes)

    def vid(i, j, k):
        return (i * nyp + j) * nzp + k

    # Layer interfaces along y (component side at 0).
    y_comp = g.comp_h
    y_pcb = g.comp_h + g.pcb_t
    y_base = y_pcb + g.base_t
    y_tim = y_base + g.tim_t
    y_wall = y_tim + g.wall_t

    hexes, mat = [], []
    for i in range(nxp - 1):
        for j in range(nyp - 1):
            for k in range(nzp - 1):
                hexes.append([
                    vid(i, j, k),     vid(i + 1, j, k),
                    vid(i + 1, j + 1, k), vid(i, j + 1, k),
                    vid(i, j, k + 1), vid(i + 1, j, k + 1),
                    vid(i + 1, j + 1, k + 1), vid(i, j + 1, k + 1),
                ])
                xc = 0.5 * (x_nodes[i] + x_nodes[i + 1])
                yc = 0.5 * (y_nodes[j] + y_nodes[j + 1])
                zc = 0.5 * (z_nodes[k] + z_nodes[k + 1])
                under = _footprint_at(xc, zc)
                if yc <= y_comp:
                    mat.append(MAT_ID["component"] if under else MAT_ID["gas"])
                elif yc <= y_pcb:
                    mat.append(MAT_ID["via"] if (under and VIA_COUPLED)
                               else MAT_ID["fr4"])
                elif yc <= y_base:
                    mat.append(MAT_ID["al"])
                elif yc <= y_tim:
                    mat.append(MAT_ID["tim"])
                else:
                    mat.append(MAT_ID["ss316"])

    hexes = np.array(hexes, dtype=np.int64)
    mat = np.array(mat, dtype=np.int32)
    y_layers = dict(comp_top=y_comp, pcb_top=y_pcb, base_top=y_base,
                    tim_top=y_tim, wall_top=y_wall)
    return points, hexes, mat, y_layers


def write_parametric_vtk(out_vtk: str):
    points, hexes, mat, _ = parametric_mesh()
    mesh = meshio.Mesh(points=points, cells=[("hexahedron", hexes)],
                       cell_data={"mat_id": [mat]})
    mesh.write(out_vtk)
    return out_vtk, points, hexes, mat


if __name__ == "__main__":
    out, pts, hx, mat = write_parametric_vtk("mesh_parametric.vtk")
    vals, counts = np.unique(mat, return_counts=True)
    inv = {v: k for k, v in MAT_ID.items()}
    print(f"Wrote {out}: {len(pts)} nodes, {len(hx)} hex cells")
    for v, c in zip(vals, counts):
        print(f"  mat {v} ({inv[v]:6s}): {c} cells")
