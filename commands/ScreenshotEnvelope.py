import adsk.core, os
from ..config import FINAL_PATH
import time


def apply_camera(vp, cam):
    cam.isSmoothTransition = False  # important: don’t animate
    vp.camera = cam

    adsk.doEvents()
    vp.refresh()
    adsk.doEvents()

    vp.camera = vp.camera
    adsk.doEvents()
    vp.refresh()
    adsk.doEvents()


def _pump_events_for(seconds: float) -> None:
    end_time = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < end_time:
        adsk.doEvents()


def screenshotEnvelope(
    length_in, width_in, plate_id, *, settle_s: float = 0.0, debug: bool = False
):
    app = adsk.core.Application.get()
    ui = app.userInterface
    vp = app.activeViewport

    length_cm = float(length_in) * 2.54
    width_cm = float(width_in) * 2.54

    cx, cy, cz = 40.0 + length_cm / 2, -1.27 + width_cm / 2, 0.0

    out_w = 800
    if length_cm <= 0 or width_cm <= 0:
        raise ValueError(
            f"Invalid plate size: length={length_in!r}, width={width_in!r}"
        )
    out_h = int(round(out_w * (width_cm / length_cm)))

    _pump_events_for(settle_s)

    cam = vp.camera  # copy
    cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
    cam.isFitView = False
    cam.isSmoothTransition = False
    app.log(f"Setting camera eye to ({cx}, {cy}, {cz + 100.0})")
    cam.target = adsk.core.Point3D.create(cx, cy, cz)
    cam.eye = adsk.core.Point3D.create(cx, cy, cz + 100.0)

    cam.upVector = adsk.core.Vector3D.create(0, 1, 0)
    apply_camera(vp, cam)

    cam = vp.camera  # copy (Fusion can normalize/adjust camera on assignment)
    cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
    cam.isFitView = False
    cam.isSmoothTransition = False
    app.log(f"Setting extents to {length_cm} cm x {width_cm} cm")
    cam.setExtents(length_cm, width_cm)
    apply_camera(vp, cam)

    out_path = os.path.join(FINAL_PATH, f"{plate_id}.png")
    ok = vp.saveAsImageFile(out_path, out_w, out_h)
    if not ok:
        raise RuntimeError("saveAsImageFile returned False")
    return out_path
