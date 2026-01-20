from ..commands.MultiImport import importFiles
from ..commands.AutoArrange import AutoArrange
from ..commands.ScreenshotEnvelope import screenshotEnvelope
import adsk.core, adsk.fusion, adsk.cam, traceback
from ..config import *
from .job_status import ensure_completion_response, send_job_error
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
        resp = session.get(f"{BASE_URL}/api/plates/{plate_id}", timeout=30)
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
        oversized_parts = []  # Parts that are too big for the plate or can't be arranged
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

        
        if plate_data and isinstance(plate_data, dict):
            length = float(plate_data.get("length", data["payload"].get("length", 24)))
            width = float(plate_data.get("width", data["payload"].get("width", 48)))
        else:
            length = float(data["payload"].get("length", 24))
            width = float(data["payload"].get("width", 48))

        # Get all occurrences before arranging to track what gets placed
        all_occurrences = list(comp.allOccurrences)
        all_part_names = [
            occ.bRepBodies.item(0).parentComponent.name
            for occ in all_occurrences
            if occ.bRepBodies.count > 0
        ]

        # Track parts in Envelope1 (successfully arranged on plate)
        arranged_on_plate = []
        # Track parts in other envelopes (excess - overflow to other plates)
        excess_occurances = []
        # Flag for complete arrange failure
        arrange_failed_completely = False

        try:
            arrange = AutoArrange(length, width)
        except RuntimeError as e:
            error_msg = str(e)
            app.log(f"AutoArrange failed completely: {error_msg}")
            # All parts failed to arrange - mark them all as oversized
            arrange_failed_completely = True
            arrange = None

        if arrange_failed_completely or arrange is None:
            # All parts couldn't be arranged - mark all as oversized
            oversized_occurances = all_part_names[:]
        else:
            for envelope in arrange.resultEnvelopes:
                app.log(f"Arranging envelope {envelope.name}")
                if "Envelope1" in envelope.name:
                    # Parts that fit on the main plate
                    for occ in envelope.occurrences:
                        arranged_on_plate.append(
                            occ.occurrence.bRepBodies.item(0).parentComponent.name
                        )
                else:
                    # Parts that overflow to other envelopes (excess)
                    for occ in envelope.occurrences:
                        excess_occurances.append(
                            occ.occurrence.bRepBodies.item(0).parentComponent.name
                        )

            # Find parts that weren't arranged at all (not in any envelope)
            # These are oversized parts that couldn't fit
            all_arranged = set(arranged_on_plate + excess_occurances)
            oversized_occurances = [
                name for name in all_part_names
                if name not in all_arranged
            ]

        # Process excess parts (overflow to other envelopes)
        excess_occurances = [str(x).split(" ")[0] for x in excess_occurances]
        excess_occurances, excess_quantity = unique(excess_occurances)
        for part_name, qty in zip(excess_occurances, excess_quantity):
            try:
                part_id = int(part_name)
            except Exception:
                continue
            excess_parts.append(
                {
                    "part_id": part_id,
                    "quantity": int(qty),
                }
            )

        # Process oversized parts (couldn't be arranged at all)
        oversized_occurances = [str(x).split(" ")[0] for x in oversized_occurances]
        oversized_occurances, oversized_quantity = unique(oversized_occurances)
        for part_name, qty in zip(oversized_occurances, oversized_quantity):
            try:
                part_id = int(part_name)
            except Exception:
                continue
            oversized_parts.append(
                {
                    "part_id": part_id,
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

        has_excess = len(excess_parts) > 0
        has_oversized = len(oversized_parts) > 0

        if not has_excess and not has_oversized:
            with open(screenshot_path, "rb") as screenshot_file:
                resp = session.post(
                    f"{BASE_URL}/api/jobs/complete",
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
        else:
            # Build error message based on what failed
            if arrange_failed_completely:
                error_msg = "No parts could be arranged. Check the size of the parts and the size of the plate."
            elif has_oversized and has_excess:
                error_msg = "Some parts are too large for the plate and others did not fit"
            elif has_oversized:
                error_msg = "Some parts are too large to fit on the plate"
            else:
                error_msg = "Excess parts detected"

            resp = session.post(
                f"{BASE_URL}/api/jobs/complete",
                files={
                    "data": (
                        None,
                        json.dumps(
                            {
                                "error": error_msg,
                                "excess_parts": excess_parts,
                                "oversized_parts": oversized_parts,
                            }
                        ),
                        "application/json",
                    )
                },
                timeout=30,
            )
        app.log(str(resp.status_code) + " " + resp.reason)
        plate_context = data["payload"].get("plate_id") or data.get("id")
        context_label = (
            f"Plate {plate_context} completion upload"
            if plate_context
            else "Plate completion upload"
        )
        ensure_completion_response(session, resp, context_label)
    except Exception:
        if app:
            app.log('helolololo')
            app.log("Failed:\n{}".format(traceback.format_exc()))
        send_job_error(session, traceback.format_exc())
