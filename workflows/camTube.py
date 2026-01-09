import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os
import shutil
import time

from ..commands.MultiImport import importFiles
from ..commands.NewNCProgram import export
from ..commands.DeleteToolpaths import DeleteToolpaths
from ..commands.HandleTube import handleTube
from ..config import FINAL_PATH, INITIAL_PATH, TEMP_PATH
from .importPlate import clear_design_nuke


def _delete_all(coll) -> None:
    for i in range(coll.count - 1, -1, -1):
        try:
            coll.item(i).deleteMe()
        except Exception:
            pass


def clear_cam_nuke(doc: adsk.core.Document) -> None:
    try:
        cam = adsk.cam.CAM.cast(doc.products.itemByProductType("CAMProductType"))
        if not cam:
            return
        _delete_all(cam.ncPrograms)
        _delete_all(cam.setups)
    except Exception:
        pass


def _normalize_assignments(payload: dict) -> list[dict]:
    def normalize_quantity(value) -> int:
        if value is None:
            return 1
        if isinstance(value, dict):
            for key in ("count", "qty", "quantity", "value", "n"):
                if key in value:
                    return normalize_quantity(value.get(key))
            total = 0
            for v in value.values():
                try:
                    total += int(v)
                except Exception:
                    pass
            return total or 1
        try:
            return int(value)
        except Exception:
            return 1

    assignments = payload.get("assignments")
    if isinstance(assignments, list):
        normalized = []
        for assignment in assignments:
            if not isinstance(assignment, dict):
                continue
            part_id = (
                assignment.get("part_id")
                or assignment.get("partId")
                or assignment.get("name")
            )
            if part_id is None:
                continue
            normalized.append(
                {
                    "part_id": part_id,
                    "quantity": normalize_quantity(assignment.get("quantity", 1)),
                }
            )
        return normalized

    parts = payload.get("parts")
    if not isinstance(parts, list):
        return []

    normalized = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_id = part.get("part_id") or part.get("partId") or part.get("name")
        if part_id is None:
            continue
        normalized.append(
            {
                "part_id": part_id,
                "quantity": normalize_quantity(part.get("quantity", 1)),
            }
        )
    return normalized


def _get(payload: dict, *keys: str, default=None):
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def start(data, session):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        try:
            ui.workspaces.itemById("FusionSolidEnvironment").activate()
            adsk.doEvents()
        except Exception:
            pass

        if app.documents.count == 0:
            app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        else:
            app.documents.item(0).activate()

        doc = app.activeDocument
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType("DesignProductType")
        )
        if not design:
            design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise RuntimeError("No active Design product.")

        clear_cam_nuke(doc)
        clear_design_nuke(design)
        time.sleep(1.0)

        assignments = _normalize_assignments(payload)
        importFiles(
            [
                os.path.join(INITIAL_PATH, f"{child['part_id']}.step")
                for child in assignments
            ],
            [child.get("quantity", 1) for child in assignments],
        )

        handleTube()
        DeleteToolpaths()
        plate_id = str(
            _get(
                payload,
                "plate_id",
                "plateId",
                "tube_id",
                "tubeId",
                default="cam_tube",
            )
        )

        export_dir = os.path.join(TEMP_PATH, plate_id)
        try:
            shutil.rmtree(export_dir)
        except FileNotFoundError:
            pass

        export(plate_id)

        zip_base = os.path.join(FINAL_PATH, plate_id)
        zip_path = f"{zip_base}.zip"
        try:
            os.remove(zip_path)
        except FileNotFoundError:
            pass

        zip_path = shutil.make_archive(zip_base, "zip", export_dir)
        shutil.rmtree(export_dir, ignore_errors=True)

        with open(zip_path, "rb") as bundle_file:
            resp = session.post(
                "http://localhost:3000/api/jobs/complete",
                files={
                    "data": (
                        None,
                        json.dumps({}),
                        "application/json",
                    ),
                    "file": (
                        f"{plate_id}.zip",
                        bundle_file,
                        "application/zip",
                    ),
                },
                timeout=30,
            )
        app.log(str(resp.status_code) + " " + resp.reason)

        try:
            if resp.ok:
                os.remove(zip_path)
        except Exception:
            pass

        try:
            ui.workspaces.itemById("FusionSolidEnvironment").activate()
        except Exception:
            pass

    except Exception as e:
        if app:
            app.log("Failed:\n{}".format(traceback.format_exc()))
