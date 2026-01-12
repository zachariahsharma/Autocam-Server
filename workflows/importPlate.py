from ..commands.MultiImport import importFiles
from ..commands.AutoArrange import AutoArrange
from ..commands.ScreenshotEnvelope import screenshotEnvelope
import adsk.core, adsk.fusion, adsk.cam, traceback
from ..config import *
import sys
from ..commands.Orientation import orient_plate_pocket_side_up
import time

sys.path.append(OVERRIDE_PATH)

import json
import os
import requests
from typing import Optional


def _delete_all(coll):
    for i in range(coll.count - 1, -1, -1):
        try:
            coll.item(i).deleteMe()
        except:
            pass


def clear_design_nuke(design: adsk.fusion.Design):
    adsk.doEvents()
    root = design.rootComponent
    _delete_all(root.occurrences)
    _delete_all(root.bRepBodies)
    _delete_all(root.sketches)
    _delete_all(root.constructionPlanes)
    _delete_all(root.constructionAxes)
    _delete_all(root.constructionPoints)
    _delete_all(root.joints)
    _delete_all(root.features)
    _delete_all(root.occurrences)

    adsk.doEvents()


def unique(items):
    counts_map = {}
    for x in items:
        counts_map[x] = counts_map.get(x, 0) + 1

    unique_values = sorted(counts_map.keys())
    counts = [counts_map[v] for v in unique_values]
    return unique_values, counts


def _normalize_quantity(value) -> int:
    if value is None:
        return 1
    if isinstance(value, dict):
        for key in ("count", "qty", "quantity", "value", "n"):
            if key in value:
                return _normalize_quantity(value.get(key))
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


def _fetch_plate_data(session: requests.Session, plate_id: int) -> Optional[dict]:
    """Fetch plate data from API and return plate info with length, width, and true_depth."""
    try:
        resp = session.get(f"http://localhost:3000/api/plates/{plate_id}", timeout=30)
        resp.raise_for_status()
        plate_data = resp.json()
        if not isinstance(plate_data, dict):
            return None
        return plate_data
    except Exception:
        return None


def start(data, session):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        excess_parts = []
        doc = app.documents.item(0).activate()
        design = adsk.fusion.Design.cast(app.activeProduct)
        clear_design_nuke(design)
        time.sleep(1.0)
        importFiles(
            [
                os.path.join(INITIAL_PATH, str(child["part_id"]) + ".step")
                for child in data["payload"]["assignments"]
            ],
            [
                _normalize_quantity(child.get("quantity", 1))
                for child in data["payload"]["assignments"]
            ],
        )
        comp: adsk.fusion.Component = app.activeProduct.rootComponent
        for occ in comp.allOccurrences:
            res = orient_plate_pocket_side_up(occ)
        
        # Fetch plate data from API to get actual length and width
        plate_id_raw = data["payload"].get("plate_id") or data["payload"].get("plateId")
        plate_data = None
        if plate_id_raw is not None:
            try:
                plate_id_int = int(plate_id_raw)
                plate_data = _fetch_plate_data(session, plate_id_int)
            except Exception:
                pass
        
        # Use plate data from API if available, otherwise fall back to payload or defaults
        if plate_data and isinstance(plate_data, dict):
            length = float(plate_data.get("length", data["payload"].get("length", 24)))
            width = float(plate_data.get("width", data["payload"].get("width", 48)))
        else:
            length = float(data["payload"].get("length", 24))
            width = float(data["payload"].get("width", 48))
        
        arrange = AutoArrange(length, width)
        occurances = []
        for envelope in arrange.resultEnvelopes:
            app.log(f"Arranging envelope {envelope.name}")
            if "Envelope1" not in envelope.name:
                for occ in envelope.occurrences:
                    occurances.append(
                        occ.occurrence.bRepBodies.item(0).parentComponent.name
                    )
        occurances = [str(x).split(" ")[0] for x in occurances]
        occurances, quantity = unique(occurances)
        for part_name, qty in zip(occurances, quantity):
            excess_parts.append(
                {
                    "partId": part_name,
                    "quantity": int(qty),
                }
            )

        screenshot_path = ""
        screenshot_path = screenshotEnvelope(
            length,
            width,
            str(data["payload"]["plate_id"]),
        )
        # doc.close(False)
        app.log("EXCESSSSSSS: " + str(excess_parts))
        app.log("hello")

        try:
            if len(excess_parts) == 0:
                with open(screenshot_path, "rb") as screenshot_file:
                    resp = session.post(
                        "http://localhost:3000/api/jobs/complete",
                        files={
                            "data": (
                                None,
                                json.dumps({}),
                                "application/json",
                            ),
                            "file": (
                                f"{data['payload']['plate_id']}.png",
                                screenshot_file,
                                "image/png",
                            ),
                        },
                        timeout=30,
                    )
            elif len(excess_parts) > 0:
                resp = session.post(
                    "http://localhost:3000/api/jobs/complete",
                    data={
                        "excessParts": json.dumps(excess_parts),
                        "error": "Excess parts detected",
                    },
                    files={},
                    timeout=30,
                )
        except Exception as e:
            app.log("Error during request: " + str(e))
            raise e
        # for screenshot in screenshots.values():
        #     try:
        #         os.remove(screenshot)
        #     except:
        #         pass
        app.log(str(resp.status_code) + " " + resp.reason)
    except Exception as e:
        if app:
            app.log("Failed:\n{}".format(traceback.format_exc()))
            session.post(
                "http://localhost:3000/api/jobs/complete",
                files={
                    "data": (
                        None,
                        json.dumps({"error": traceback.format_exc()}),
                        "application/json",
                    )
                },
                timeout=30,
            )
