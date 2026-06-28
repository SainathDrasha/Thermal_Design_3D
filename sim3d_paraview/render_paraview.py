"""Stage 3 (ParaView): render each <case>.vtu to a labelled temperature PNG.

Run under ParaView's interpreter:
    pvpython render_paraview.py

For every results/<case>.vtu this:
  * loads the VTU and locates the CalculiX nodal-temperature array ('NT'),
  * adds a Calculator that converts Kelvin -> Celsius (display only; the solver
    field is untouched),
  * colours the field with the Turbo colour map and shows a scalar bar,
  * sets an isometric view with an orientation axis,
  * annotates the peak temperature, and
  * saves results/<case>.png.

Only ParaView's documented `paraview.simple` API is used. The temperature array
is auto-detected, so this still works if a future CalculiX/ccx2paraview version
renames the field.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import CASES, RESULTS

sys.path.insert(0, os.path.join(HERE, "..", "sim3d"))  # config.py
from config import T_J_MAX_C

from paraview.simple import (
    Calculator, Clip, ColorBy, Contour, Delete, GetActiveCamera,
    GetColorTransferFunction, GetScalarBar, GetActiveViewOrCreate, GetSources,
    SaveScreenshot, SaveState, Show, Text, XMLUnstructuredGridReader,
)

IMAGE_SIZE = [1600, 1000]

# Cut-away clip: the heat sources sit *inside* the stack, so the outer surface
# reads near-ambient and hides the gradient. A clip plane through the model
# centre exposes the interior cross-section where the peak temperature lives.
# Set USE_CLIP = False for a plain exterior render. CLIP_NORMAL is the plane
# normal in mesh axes (x=length, y=through-thickness, z=width); the default
# cuts a lengthwise vertical section that crosses the PCB heat-injection layer.
USE_CLIP = True
CLIP_NORMAL = [0.0, 0.0, 1.0]

# Over-temperature isosurface: a red surface at the junction limit marks exactly
# where the field crosses Tj_max -- the at-risk volume at a glance. Empty (no
# surface drawn) when the whole field is below the limit.
SHOW_ISOSURFACE = True
LIMIT_C = T_J_MAX_C

# Save a ParaView state (.pvsm) per case so the scene re-opens ready to
# rotate / slice / probe / plot-over-line in the GUI.
SAVE_STATE = True


def _temperature_array(reader):
    """Pick the nodal-temperature point array name from a reader's point data.

    CalculiX/ccx2paraview names it 'NT'; fall back to anything temperature-like.
    """
    names = list(reader.PointData.keys())
    for preferred in ("NT", "TEMP", "NDTEMP", "T"):
        if preferred in names:
            return preferred
    for n in names:
        if "temp" in n.lower():
            return n
    raise RuntimeError("No temperature array in point data: %s" % names)


def render_case(case, view):
    vtu = os.path.join(RESULTS, case + ".vtu")
    if not os.path.exists(vtu):
        print("[render] %s.vtu not found -- run frd_to_vtu.py first" % case)
        return False

    reader = XMLUnstructuredGridReader(FileName=[vtu])
    reader.UpdatePipeline()
    temp_k = _temperature_array(reader)

    # Kelvin -> Celsius for display; the underlying solver field is unchanged.
    calc = Calculator(Input=reader)
    calc.AttributeType = "Point Data"
    calc.ResultArrayName = "Temperature_C"
    calc.Function = '"%s" - 273.15' % temp_k
    calc.UpdatePipeline()

    tmin, tmax = calc.PointData["Temperature_C"].GetRange()

    # Cut-away so the buried hot spots are visible (see USE_CLIP above).
    if USE_CLIP:
        b = calc.GetDataInformation().GetBounds()  # xmin,xmax,ymin,ymax,zmin,zmax
        source = Clip(Input=calc)
        source.ClipType = "Plane"
        source.ClipType.Origin = [(b[0] + b[1]) / 2.0,
                                  (b[2] + b[3]) / 2.0,
                                  (b[4] + b[5]) / 2.0]
        source.ClipType.Normal = CLIP_NORMAL
        source.UpdatePipeline()
    else:
        source = calc

    disp = Show(source, view)
    ColorBy(disp, ("POINTS", "Temperature_C"))
    disp.RescaleTransferFunctionToDataRange(True, False)
    disp.SetScalarBarVisibility(view, True)

    lut = GetColorTransferFunction("Temperature_C")
    lut.ApplyPreset("Turbo", True)
    lut.RescaleTransferFunction(tmin, tmax)

    bar = GetScalarBar(lut, view)
    bar.Title = "Temperature"
    bar.ComponentTitle = "C"

    # Over-temperature isosurface at the junction limit (full field, so it shows
    # the whole at-risk boundary); the clip is made translucent so it shows
    # through. Drawn only when the field actually crosses the limit.
    if SHOW_ISOSURFACE and tmin < LIMIT_C < tmax:
        iso = Contour(Input=calc)
        iso.ContourBy = ["POINTS", "Temperature_C"]
        iso.Isosurfaces = [LIMIT_C]
        iso.UpdatePipeline()
        iso_disp = Show(iso, view)
        ColorBy(iso_disp, None)                 # solid red, not the field
        iso_disp.AmbientColor = [1.0, 0.0, 0.0]
        iso_disp.DiffuseColor = [1.0, 0.0, 0.0]
        disp.Opacity = 0.45

    # Peak-temperature label.
    label = Text()
    label.Text = ("%s\nTmax = %.1f C   Tmin = %.1f C   (limit %.0f C)"
                  % (case, tmax, tmin, LIMIT_C))
    label_disp = Show(label, view)
    try:
        label_disp.WindowLocation = "Upper Left Corner"
        label_disp.FontSize = 14
    except Exception:
        pass

    # Isometric view, fitted.
    view.ResetCamera()
    cam = GetActiveCamera()
    cam.Azimuth(45)
    cam.Elevation(25)
    view.ResetCamera()

    png = os.path.join(RESULTS, case + ".png")
    SaveScreenshot(png, view, ImageResolution=IMAGE_SIZE)
    print("[render] %-8s Tmax=%.1f C -> %s.png" % (case, tmax, case))

    if SAVE_STATE:
        state = os.path.join(RESULTS, case + ".pvsm")
        SaveState(state)
        print("[render] %-8s state -> %s.pvsm" % (case, case))

    # Clear the pipeline so each case's render and saved state are self-contained.
    for src in list(GetSources().values()):
        Delete(src)
    return True


def main():
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = IMAGE_SIZE
    view.OrientationAxesVisibility = 1
    # Force a white background (override the colour-palette default, whose
    # property names vary across ParaView versions -- set what exists).
    for prop, val in (("UseColorPaletteForBackground", 0),
                      ("BackgroundColorMode", "Single Color")):
        try:
            setattr(view, prop, val)
        except Exception:
            pass
    view.Background = [1.0, 1.0, 1.0]
    any_done = False
    for case in CASES:
        any_done |= render_case(case, view)
    if not any_done:
        sys.exit(1)
    print("Done. PNGs written to %s" % RESULTS)


if __name__ == "__main__":
    main()
