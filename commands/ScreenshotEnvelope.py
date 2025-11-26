import adsk.core, adsk.fusion, adsk.cam, traceback
import os, platform, math

# === CONFIG: Your region on the XY plane ===
X_OFFSET_CM = 40.0  # 40 cm X offset (left edge)

# Output image size (keep aspect = height/width). 1000x2000 is crisp and lightweight.
OUT_WIDTH_PX = 800
OUT_HEIGHT_PX = 2000

# Optional: file name


# === Helpers ===
def _temp_path():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "../temp")


def _cm(val_in_inches: float) -> float:
    return val_in_inches * 2.54


def screenshotEnvelope(height, width, plateid):
    app = adsk.core.Application.get()
    ui = app.userInterface
    vp = app.activeViewport

    # Convert given size to centimeters (Fusion internal length unit)
    width_cm = _cm(width)
    height_cm = _cm(height)

    # Center of the rectangle assuming its lower-left corner at (X_OFFSET_CM, 0)
    cx = X_OFFSET_CM + (width_cm / 2.0)
    cy = 0.0 + height_cm / 2.0
    cz = 0.0

    desired_aspect = height_cm / width_cm
    # If caller-specified OUT_WIDTH/HEIGHT don't match aspect, auto-fix height
    out_w = OUT_WIDTH_PX
    out_h = int(round(out_w * desired_aspect))

    # Build a top-down orthographic camera looking at the XY plane
    cam = vp.camera
    cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
    cam.isFitView = False
    # Target = center of the rectangle; Eye = slightly above along +Z
    target = adsk.core.Point3D.create(cx, cy, cz)
    eye = adsk.core.Point3D.create(
        cx, cy, cz + 1
    )  # 100 cm above; distance doesn't affect ortho scale
    cam.target = target
    cam.eye = eye

    # Up vector along +Y to Akeep "height" vertical on screen
    cam.upVector = adsk.core.Vector3D.create(0, 1, 0)
    cam.setExtents(width_cm, height_cm)
    # app.log(f"Camera extents set to {cam.getExtents()[1]} cm width x {cam.getExtents()[2]} cm height")
    # Apply camera and refresh
    vp.camera = cam
    adsk.doEvents()
    vp.refresh()

    # Save the image to temp
    temp = _temp_path()
    if not os.path.isdir(temp):
        os.makedirs(temp, exist_ok=True)
    out_path = os.path.join(temp, plateid + ".png")

    # SaveAsImage(width, height) captures exactly what's framed by the camera
    ok = vp.saveAsImageFile(out_path, out_w, out_h)
    if not ok:
        raise RuntimeError("Viewport.saveAsImage returned False (image not saved).")