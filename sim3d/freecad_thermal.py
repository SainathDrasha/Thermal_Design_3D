"""
FreeCAD + CalculiX 3D steady-state thermal interface for the SEM 300 W module.

Division of labour (as requested):
  * Python  -> geometry construction and all physical inputs. The layered
               parametric stack and the per-device heat-injection volumes are
               built here from the existing `config.py` (single source of truth,
               shared with the SfePy pipeline).
  * FreeCAD -> meshing (Gmsh) and FEM model assembly via the documented
               scripting API (ObjectsFem / femtools), exactly the workflow of
               the FreeCAD wiki "FEM Tutorial Python".
  * CalculiX-> the physics: a pure heat-transfer steady-state conduction solve
               (`*HEAT TRANSFER, STEADY STATE`), run head-less through ccxtools.

Physics modelled (identical to the validated SfePy model in solve.py):
    div(k grad T) = 0   in the layered stack
    device losses injected as volumetric sources in the PCB under each footprint
    convective (film) BC on the housing outer face; all other faces adiabatic.

Run, head-less (terminal):
    freecadcmd freecad_thermal.py

Run inside the FreeCAD GUI (so you can inspect geometry, mesh and the
temperature field interactively):
    * Macro menu -> Macros... -> add/point to this file -> Execute, or
    * open the Python console (View -> Panels -> Python console) and run:
        exec(open("/full/path/to/freecad_thermal.py").read())
    * to build/solve a single case and leave it open for inspection:
        import freecad_thermal as ft
        ft.solve_case("subsea", ft.os.path.dirname(ft.__file__) + "/freecad_out")
  When the GUI is up the script activates the analysis and fits the view; click
  the result object and choose "Temperature" to colour the field. CalculiX
  handles all meshing/solving; Python only builds the geometry and inputs.

API note: every FreeCAD call below was cross-checked against the FreeCAD
main-branch source (ObjectsFem.py, femobjects/, femsolver/calculix/).
Pure-conduction path is selected with AnalysisType="thermomech" +
ThermoMechType="pure heat transfer" + ThermoMechSteadyState=True, which the
CalculiX writer turns into "*HEAT TRANSFER, STEADY STATE".
"""

import os
import sys

import FreeCAD as App
import ObjectsFem
from femmesh.gmshtools import GmshTools
from femtools import ccxtools

# config.py lives in this same folder; reuse it verbatim.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    MATERIALS, POWER_MAP_2SF, GEOM, CASES, VIA_COUPLED,
    power_total, effective_h, c_to_k,
)

MM = 1000.0  # config is SI (metres); FreeCAD geometry is in millimetres.

# Layer stack along +y, mirroring config.Geometry. Each entry:
#   (material_key, y_bottom, y_top)  in metres.
_LAYERS = [
    ("fr4",   0.0,                                   GEOM.y_pcb_top),
    ("al",    GEOM.y_pcb_top,                        GEOM.y_base_top),
    ("tim",   GEOM.y_base_top,                       GEOM.y_tim_top),
    ("ss316", GEOM.y_tim_top,                        GEOM.y_wall_top),
]
_PCB_TOP_Y = GEOM.y_pcb_top          # device-injection volumes span 0..pcb_t
_OUTER_FACE_Y = GEOM.y_wall_top      # convective housing face (top of stack)
_TOL = 1e-6 * MM                     # geometric tolerance in mm


def _box(doc, name, x0, y0, z0, dx, dy, dz):
    """Add an axis-aligned Part::Box (inputs in metres, placed in mm).

    Config axes map straight onto FreeCAD global axes: X=board length (config x),
    Y=through-thickness/stack (config y), Z=board width (config z). Part::Box
    dimensions are Length=X, Width=Y, Height=Z.
    """
    obj = doc.addObject("Part::Box", name)
    obj.Length, obj.Width, obj.Height = dx * MM, dy * MM, dz * MM
    obj.Placement.Base = App.Vector(x0 * MM, y0 * MM, z0 * MM)
    return obj


def build_geometry(doc):
    """Build the conformal layered stack with per-device injection volumes.

    Returns (frag_obj, classify) where classify(solid) -> ("material_key",
    device_or_None) maps each solid of the fragmented shape to its material and,
    for PCB-footprint volumes, the Source it carries.
    """
    pieces = []

    # Full-area layer blocks (origin corner at x=0, z=0).
    for key, y0, y1 in _LAYERS:
        pieces.append(_box(doc, f"layer_{key}", 0.0, y0, 0.0,
                           GEOM.board_len, y1 - y0, GEOM.board_wid))

    # Per-device injection volumes through the PCB thickness (0..pcb_t).
    for s in POWER_MAP_2SF:
        pieces.append(_box(doc, f"dev_{s.name}",
                           s.x_center - s.x_len / 2.0, 0.0, s.z_center - s.z_len / 2.0,
                           s.x_len, _PCB_TOP_Y, s.z_len))
    doc.recompute()

    # Boolean fragments -> single conformal compound (shared interface faces),
    # required for a node-matched FEM mesh across material boundaries.
    import BOPTools.SplitFeatures as SF
    frag = SF.makeBooleanFragments(name="Fragments")
    frag.Objects = pieces
    doc.recompute()

    # Consolidate the fragmented compound into ONE static Part::Feature used for
    # BOTH the mesh and every FEM reference. The mesh geometry and the
    # material/load References must be the same object; otherwise the solid
    # subnames resolve against a different object than the one meshed and every
    # element comes out with "no material assigned" in CalculiX.
    geo = doc.addObject("Part::Feature", "Stack")
    geo.Shape = frag.Shape
    doc.recompute()

    # Warn (not fail) if any two device footprints overlap: a boolean fragment
    # then splits them into shared sub-solids whose centre lies in both boxes.
    # The classifier below stays robust to this (first match wins, heat still
    # injected), but the geometry is ambiguous and worth surfacing.
    for i, a in enumerate(POWER_MAP_2SF):
        for b in POWER_MAP_2SF[i + 1:]:
            ox = min(a.x_center + a.x_len / 2, b.x_center + b.x_len / 2) - \
                max(a.x_center - a.x_len / 2, b.x_center - b.x_len / 2)
            oz = min(a.z_center + a.z_len / 2, b.z_center + b.z_len / 2) - \
                max(a.z_center - a.z_len / 2, b.z_center - b.z_len / 2)
            if ox > 1e-9 and oz > 1e-9:
                App.Console.PrintWarning(
                    "Footprints overlap: %s <> %s (%.1f x %.1f mm)\n"
                    % (a.name, b.name, ox * MM, oz * MM))

    def classify(solid):
        """Map a sub-solid to (material_key, device_or_None).

        Device match is by footprint *containment* of the solid centre (not an
        exact centre equality), so a PCB sub-solid that boolean fragmentation
        split off is still attributed to its device. First device wins, which
        keeps an overlapping pair deterministic instead of dropping heat.

        When VIA_COUPLED, a device's through-PCB column is given the "via"
        material (effective conductivity of the filled thermal-via array under
        the pad, config.K_VIA) instead of bare FR-4 -- the realistic bottom-
        cooled path. Set VIA_COUPLED=False in config for the pessimistic
        top-mount-through-FR-4 worst case.
        """
        c = solid.CenterOfMass
        for key, y0, y1 in _LAYERS:
            if y0 * MM - _TOL <= c.y <= y1 * MM + _TOL:
                if key != "fr4":
                    return key, None
                for s in POWER_MAP_2SF:
                    if (abs(c.x - s.x_center * MM) <= s.x_len / 2 * MM + _TOL and
                            abs(c.z - s.z_center * MM) <= s.z_len / 2 * MM + _TOL):
                        # Column material by cooling path (both conduct to the
                        # baseplate; dry N2 is not a heat path):
                        #   "pad"        -> thermal gap-pad column (magnetics)
                        #   "conduction" -> via column (power semis), if VIA_COUPLED
                        if s.cooling == "pad":
                            return "pad", s
                        via = VIA_COUPLED and s.cooling == "conduction"
                        return ("via" if via else "fr4"), s
                return key, None
        return "fr4", None  # fallback: treat stray slivers as PCB

    return geo, classify


def _outer_face_names(shape):
    """Subelement names of the planar housing outer face (top of stack)."""
    names = []
    for i, f in enumerate(shape.Faces, start=1):
        bb = f.BoundBox
        if abs(bb.YMax - _OUTER_FACE_Y * MM) < _TOL and bb.YLength < _TOL:
            names.append(f"Face{i}")
    return names


def setup_analysis(doc, geo, classify, case, mesh_mm=6.0, second_order=False):
    """Assemble the FreeCAD FEM model: solver, materials, sources, BC, mesh.

    mesh_mm      : Gmsh CharacteristicLengthMax in mm (smaller = finer).
    second_order : True -> quadratic C3D10 tets (accurate gradients), else C3D4.
    """
    shape = geo.Shape

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    # Solver: pure-conduction steady state (well-tested CcxTools object).
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiX")
    solver.AnalysisType = "thermomech"
    solver.ThermoMechType = "pure heat transfer"   # -> *HEAT TRANSFER
    solver.ThermoMechSteadyState = True            # -> , STEADY STATE
    solver.GeometricalNonlinearity = "linear"
    solver.MatrixSolverType = "default"
    solver.IterationsControlParameterTimeUse = False

    analysis.addObject(solver)
    # Required by CalculiX for thermomechanical analyses, even steady-state.
    # NB: released FreeCAD 1.0 names this property "initialTemperature"
    # (lowercase); the dev branch renamed it to "InitialTemperature".
    t0 = ObjectsFem.makeConstraintInitialTemperature(doc, "InitialTemperature")
    t0.initialTemperature = f"{c_to_k(case.t_inf_c)} K"
    analysis.addObject(t0)

    # Group solid subelement names by material, and group every device's
    # footprint sub-solids under its name (a footprint may be split into
    # several solids by the boolean fragmentation).
    mat_solids, dev_subs = {}, {}
    for idx, sol in enumerate(shape.Solids, start=1):
        sub = f"Solid{idx}"
        key, dev = classify(sol)
        mat_solids.setdefault(key, []).append(sub)
        if dev is not None:
            dev_subs.setdefault(dev.name, []).append(sub)

    # Materials. The steady-state conduction result depends only on
    # ThermalConductivity; the other keys are written by the CalculiX exporter
    # for every solid in a thermomech step, so nominal placeholders are supplied
    # and flagged. [ASSUMED-IRRELEVANT] = required by the writer, not used by the
    # steady-state physics (verified in write_femelement_material.py).
    #
    # FreeCAD assigns every mesh element not explicitly referenced by a material
    # to the ONE material that has empty References (get_femelement_sets, the
    # catch-all). fr4 is the catch-all (the PCB remainder, hardest to match by
    # node); al/tim/ss316 and -- when VIA_COUPLED -- the per-device "via" columns
    # are referenced explicitly. This guarantees 100% element coverage (no
    # "no material assigned" elements).
    CATCH_ALL = "fr4"
    for key, subs in mat_solids.items():
        m = ObjectsFem.makeMaterialSolid(doc, f"mat_{key}")
        d = m.Material
        d["Name"] = key
        d["ThermalConductivity"] = f"{MATERIALS[key]['k']} W/m/K"   # physical
        d["YoungsModulus"] = "1000 MPa"                              # [ASSUMED-IRRELEVANT]
        d["PoissonRatio"] = "0.30"                                   # [ASSUMED-IRRELEVANT]
        d["Density"] = "1000 kg/m^3"                                 # [ASSUMED-IRRELEVANT]
        d["SpecificHeat"] = "1000 J/kg/K"                            # [ASSUMED-IRRELEVANT]
        d["ThermalExpansionCoefficient"] = "0 um/m/K"               # [ASSUMED-IRRELEVANT]
        m.Material = d
        if key != CATCH_ALL:
            m.References = [(geo, list(subs))]   # explicit; fr4 stays empty
        analysis.addObject(m)

    # Device losses: ONE body heat source per device, referencing all of that
    # device's footprint sub-solids. Mode="Total Power" makes CalculiX spread
    # the loss over the referenced volume, so a split (or overlapping) footprint
    # still receives exactly its loss once -- never dropped, never double-counted.
    # Fail loudly if a device matched no solid, so a loss can never vanish
    # silently (the bug that previously dropped dcdc_sr and dcdc_transformer).
    dev_by_name = {s.name: s for s in POWER_MAP_2SF}
    missing = [n for n in dev_by_name if n not in dev_subs]
    if missing:
        raise RuntimeError(
            "No mesh solid found for device(s) %s -- check for overlapping or "
            "off-board footprints in the power map." % missing)
    injected = 0.0
    for name, subs in dev_subs.items():
        dev = dev_by_name[name]
        bhs = ObjectsFem.makeConstraintBodyHeatSource(doc, f"q_{name}")
        bhs.Mode = "Total Power"
        bhs.TotalPower = f"{dev.loss_w} W"
        bhs.References = [(geo, list(subs))]
        analysis.addObject(bhs)
        injected += dev.loss_w
    # Input accounting only (not a physics calc): confirm every watt is placed.
    if abs(injected - power_total()) > 1e-6:
        App.Console.PrintWarning(
            "Injected %.3f W != power_total %.3f W\n" % (injected, power_total()))

    # Convective (film) BC on the housing outer face; all other faces adiabatic.
    faces = _outer_face_names(shape)
    if not faces:
        raise RuntimeError("Housing outer face not found for convection BC.")
    hf = ObjectsFem.makeConstraintHeatflux(doc, "Convection")
    hf.ConstraintType = "Convection"
    hf.FilmCoef = f"{effective_h(case):.6f} W/m^2/K"  # housing-area-scaled, per config
    hf.AmbientTemp = f"{c_to_k(case.t_inf_c)} K"
    hf.References = [(geo, list(faces))]
    analysis.addObject(hf)

    # Mesh (Gmsh) on the SAME consolidated geometry object the materials and
    # loads reference -> node-matched across materials, every element tagged.
    femmesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    femmesh.Shape = geo
    femmesh.CharacteristicLengthMax = f"{mesh_mm} mm"
    if second_order:
        # Quadratic tets (C3D10). Property name verified for FreeCAD 1.x MeshGmsh;
        # guarded so a renamed property doesn't abort the solve.
        try:
            femmesh.ElementOrder = "2nd"
        except Exception as e:                        # noqa: BLE001
            App.Console.PrintWarning(f"Could not set 2nd order: {e}\n")
    doc.recompute()

    err = GmshTools(femmesh).create_mesh()
    if err:
        App.Console.PrintWarning(f"Gmsh: {err}\n")

    analysis.addObject(femmesh)
    doc.recompute()

    return analysis, solver


def solve_case(case_name, out_dir, mesh_mm=6.0, second_order=False):
    """Run one operating-environment case head-less; return a result summary."""
    case = CASES[case_name]
    doc = App.newDocument(f"sem_freecad_{case_name}")

    geo, classify = build_geometry(doc)
    analysis, solver = setup_analysis(doc, geo, classify, case,
                                      mesh_mm=mesh_mm, second_order=second_order)

    fea = ccxtools.FemToolsCcx(analysis, solver)
    fea.update_objects()
    fea.setup_working_dir(out_dir)
    fea.setup_ccx()
    msg = fea.check_prerequisites()
    if msg:
        raise RuntimeError(f"CalculiX prerequisites failed: {msg}")
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()

    result = next((o for o in analysis.Group
                   if o.isDerivedFrom("Fem::FemResultObject")
                   or o.isDerivedFrom("Fem::FemResultObjectPython")), None)
    if result is None or not result.Temperature:
        raise RuntimeError(
            f"No temperature result for '{case_name}'. CalculiX did not finish "
            f"(check the .frd/.dat/.cvg files in {out_dir}).")
    # Report CalculiX's temperature field directly. The model is fed absolute
    # Kelvin (FreeCAD's temperature properties store Kelvin), so the solver
    # returns Kelvin; the only post-processing here is a unit shift to Celsius
    # for the printout -- no physics is recomputed in Python.
    temps_c = [t - 273.15 for t in result.Temperature]

    # When run inside the FreeCAD GUI, surface the analysis in the tree and fit
    # the view so the geometry/mesh/result can be inspected interactively. The
    # guard keeps the script head-less-safe (freecadcmd / terminal).
    if App.GuiUp:
        import FemGui
        import FreeCADGui as Gui
        FemGui.setActiveAnalysis(analysis)
        Gui.activeDocument().activeView().viewIsometric()
        Gui.SendMsgToActiveView("ViewFit")

    doc.saveAs(os.path.join(out_dir, f"sem_freecad_{case_name}.FCStd"))

    return {
        "case": case_name,
        "h_eff_W_m2K": effective_h(case),
        "t_inf_C": case.t_inf_c,
        "Tmax_C": max(temps_c),
        "Tmin_C": min(temps_c),
        "n_nodes": len(temps_c),
        "inp": fea.inp_file_name,
    }


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "freecad_out")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Total injected power: {power_total():.1f} W")
    print(f"{'case':<8} {'h_eff[W/m2K]':>12} {'T_inf[C]':>9} "
          f"{'Tmax[C]':>9} {'Tmin[C]':>9} {'nodes':>8}")
    for name in ("subsea", "surface"):
        r = solve_case(name, out_dir)
        print(f"{r['case']:<8} {r['h_eff_W_m2K']:>12.1f} {r['t_inf_C']:>9.1f} "
              f"{r['Tmax_C']:>9.1f} {r['Tmin_C']:>9.1f} {r['n_nodes']:>8d}")
    print(f"\nArtifacts (.FCStd, .inp, .frd) in: {out_dir}")
    print("Tmax/Tmin are CalculiX's temperature field (Kelvin output shifted to "
          "Celsius). Open the .FCStd in the FreeCAD GUI to inspect the field.")


if __name__ == "__main__":
    main()
