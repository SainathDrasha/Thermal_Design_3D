"""
Run the whole SEM 300 W 3D thermal pipeline in one command:

    python run_all.py

Executes, in order: the Rayleigh decision-gate, the mesh build, then the
subsea + surface solves. Each stage is run exactly as if launched on its own,
so the output and the written files (mesh_parametric.vtk, result_*.vtk) are
identical to running the three scripts by hand.
"""

import runpy

STAGES = [
    ("1/4  Rayleigh decision-gate", "rayleigh.py"),
    ("2/4  Mesh build",            "mesh_gen.py"),
    ("3/4  Conduction solve",      "solve.py"),
    ("4/4  3D visualization",      "postprocess.py"),
]

for title, script in STAGES:
    print("\n" + "#" * 74)
    print(f"# {title}")
    print("#" * 74)
    runpy.run_path(script, run_name="__main__")

print("\nPipeline complete.")
print("  3D renders : view_subsea.png, view_surface.png")
print("  raw fields : result_subsea.vtk, result_surface.vtk (ParaView)")
print("  interactive: python postprocess.py --show")
