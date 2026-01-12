import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os
import shutil
import time

import requests
from typing import Optional

from ..commands.SetupGenerator import SetupGenerator
from ..commands.MultiImport import importFiles
from ..commands.NewNCProgram import export
from ..commands.DeleteToolpaths import DeleteToolpaths
from ..commands.AutoArrange import AutoArrange
from ..config import BASE_URL, FINAL_PATH, INITIAL_PATH, TEMP_PATH, TOOLS_PATH
from .importPlate import clear_design_nuke
from .templateTools import patch_cam_template_with_tool_libraries


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


def _download_tool_library_json(
    session: requests.Session, tool_id: int, dest_dir: str
) -> tuple[dict, str]:
    os.makedirs(dest_dir, exist_ok=True)
    resp = session.get(f"{BASE_URL}/api/tools/{tool_id}", timeout=30)
    resp.raise_for_status()
    info = resp.json()
    if not isinstance(info, dict):
        raise TypeError(f"Unexpected tool response: {type(info)}")

    url = info.get("file")
    if not url:
        raise ValueError("Tool response missing 'file' signed URL")

    out_path = os.path.join(dest_dir, f"{tool_id}.json")
    if not os.path.exists(out_path):
        content = requests.get(url, timeout=30).content
        with open(out_path, "wb") as f:
            f.write(content)

    return info, out_path


def _first_material_name(session: requests.Session, material_ids) -> Optional[str]:
    if not isinstance(material_ids, list) or not material_ids:
        return None
    material_id = material_ids[0]
    try:
        material_id_int = int(material_id)
    except Exception:
        return None

    resp = session.get("{BASE_URL}/api/materials", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return None
    for material in data:
        if not isinstance(material, dict):
            continue
        try:
            if int(material.get("id")) != material_id_int:
                continue
        except Exception:
            continue
        name = material.get("name")
        return str(name) if name else None
    return None


def _machine_name(session: requests.Session, machine_id) -> Optional[str]:
    if machine_id is None:
        return None
    try:
        machine_id_int = int(machine_id)
    except Exception:
        return None

    resp = session.get("{BASE_URL}/api/machines", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return None
    for machine in data:
        if not isinstance(machine, dict):
            continue
        try:
            if int(machine.get("id")) != machine_id_int:
                continue
        except Exception:
            continue
        name = machine.get("name")
        return str(name) if name else None
    return None


def _download_machine_post_processor(
    session: requests.Session, machine_id: int, dest_dir: str
) -> tuple[dict, str]:
    """Download machine post processor file from API and return machine info and file path."""
    os.makedirs(dest_dir, exist_ok=True)
    resp = session.get(f"{BASE_URL}/api/machines/{machine_id}", timeout=30)
    resp.raise_for_status()
    info = resp.json()
    if not isinstance(info, dict):
        raise TypeError(f"Unexpected machine response: {type(info)}")

    url = info.get("file")
    if not url:
        raise ValueError("Machine response missing 'file' signed URL")

    # Determine file extension from URL or default to .cps
    file_ext = ".cps"
    # if "." in url.split("?")[0]:
    #     file_ext = "." + url.split("?")[0].split(".")[-1]

    out_path = os.path.join(dest_dir, f"machine_{machine_id}{file_ext}")
    if not os.path.exists(out_path):
        content = requests.get(url, timeout=30).content
        with open(out_path, "wb") as f:
            f.write(content)

    return info, out_path


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
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        try:
            ui.workspaces.itemById("FusionSolidEnvironment").activate()
            adsk.doEvents()
        except Exception:
            pass

        # Create a new document instead of using existing one
        new_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        new_doc.activate()
        time.sleep(0.5)

        doc = app.activeDocument
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType("DesignProductType")
        )
        if not design:
            design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise RuntimeError("No active Design product.")

        # Clear design but don't nuke CAM (we're creating a new file)
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

        # Fetch plate data from API to get actual length, width, and true_depth
        plate_id_raw = _get(payload, "plate_id", "plateId")
        plate_data = None
        if plate_id_raw is not None:
            try:
                plate_id_int = int(plate_id_raw)
                plate_data = _fetch_plate_data(session, plate_id_int)
            except Exception:
                pass

        # Use plate data from API if available, otherwise fall back to payload or defaults
        if plate_data and isinstance(plate_data, dict):
            length = float(plate_data.get("length", _get(payload, "length", default=24)))
            width = float(plate_data.get("width", _get(payload, "width", default=48)))
            true_depth = float(plate_data.get("true_depth", _get(payload, "true_depth", "trueDepth", default=0.125)))
        else:
            length = float(_get(payload, "length", default=24))
            width = float(_get(payload, "width", default=48))
            true_depth = float(_get(payload, "true_depth", "trueDepth", default=0.125))

        AutoArrange(length, width)

        # Handle tool_id as a list
        tool_ids_raw = _get(payload, "tool_id", "toolId", "tool_ids")
        tool_ids = []
        if tool_ids_raw is not None:
            if isinstance(tool_ids_raw, list):
                tool_ids = [int(tid) for tid in tool_ids_raw if tid is not None]
            else:
                try:
                    tool_ids = [int(tool_ids_raw)]
                except Exception:
                    pass

        machine_id = _get(payload, "machine_id", "machineId")

        try:
            machine_id_int = int(machine_id) if machine_id is not None else None
        except Exception:
            machine_id_int = None

        material_name = None
        machine_name = None
        machine_post_processor_path = None
        template_path = os.path.join(
            os.path.dirname(__file__), "../templates/Plates.f3dhsm-template"
        )

        tool_library_paths = []
        tool_info = None
        tool_list_cache = None

        # Download machine post processor if machine_id is provided
        if machine_id_int is not None:
            try:
                machine_info, machine_post_processor_path = (
                    _download_machine_post_processor(
                        session, machine_id_int, dest_dir=TOOLS_PATH
                    )
                )
                machine_name = machine_info.get("name")
            except Exception:
                app.log(
                    "Failed to download machine post processor:\n{}".format(
                        traceback.format_exc()
                    )
                )

        # If no tool_ids provided, pick the first compatible one.
        if not tool_ids:
            try:
                resp = session.get("{BASE_URL}/api/tools", timeout=30)
                resp.raise_for_status()
                tool_list_cache = resp.json()
                if isinstance(tool_list_cache, dict) and isinstance(
                    tool_list_cache.get("data"), list
                ):
                    tool_list_cache = tool_list_cache["data"]

                if isinstance(tool_list_cache, list):
                    for lib in tool_list_cache:
                        if not isinstance(lib, dict):
                            continue
                        lib_id = lib.get("id")
                        if lib_id is None:
                            continue
                        try:
                            candidate_id = int(lib_id)
                        except Exception:
                            continue

                        if machine_id_int is not None:
                            machine_ids = lib.get("machine_ids") or []
                            try:
                                machine_ids = [int(x) for x in machine_ids]
                            except Exception:
                                machine_ids = []
                        if machine_id_int not in machine_ids:
                            continue

                        tool_ids = [candidate_id]
                        break
            except Exception:
                app.log(
                    "Failed to list tool libraries:\n{}".format(traceback.format_exc())
                )

        # Download all tool libraries for the provided tool_ids
        seen_tool_ids = set()
        for tool_id_int in tool_ids:
            if tool_id_int in seen_tool_ids:
                continue
            seen_tool_ids.add(tool_id_int)
            try:
                tool_info, tool_json_path = _download_tool_library_json(
                    session, tool_id_int, dest_dir=TOOLS_PATH
                )
                tool_library_paths.append(tool_json_path)
                # Use material from first tool library
                if material_name is None:
                    material_name = _first_material_name(
                        session, tool_info.get("material_ids")
                    )
            except Exception:
                app.log(
                    "Failed to download tool library:\n{}".format(
                        traceback.format_exc()
                    )
                )

        # If the chosen libraries don't contain every required tool, allow fallbacks.
        if tool_ids and machine_id_int is not None:
            try:
                if tool_list_cache is None:
                    resp = session.get("{BASE_URL}/api/tools", timeout=30)
                    resp.raise_for_status()
                    tool_list_cache = resp.json()
                    if isinstance(tool_list_cache, dict) and isinstance(
                        tool_list_cache.get("data"), list
                    ):
                        tool_list_cache = tool_list_cache["data"]

                material_ids_hint = []
                # Get material_ids from first tool library
                if tool_library_paths:
                    try:
                        first_tool_info, _ = _download_tool_library_json(
                            session, tool_ids[0], dest_dir=TOOLS_PATH
                        )
                        if isinstance(first_tool_info, dict) and isinstance(
                            first_tool_info.get("material_ids"), list
                        ):
                            material_ids_hint = first_tool_info.get("material_ids")
                            try:
                                material_ids_hint = [
                                    int(x) for x in material_ids_hint if x is not None
                                ]
                            except Exception:
                                material_ids_hint = []
                        else:
                            material_ids_hint = []
                    except Exception:
                        pass

                seen_ids = set(tool_ids)
                if isinstance(tool_list_cache, list):
                    for lib in tool_list_cache:
                        if not isinstance(lib, dict):
                            continue
                        lib_id = lib.get("id")
                        if lib_id is None:
                            continue
                        try:
                            lib_id_int = int(lib_id)
                        except Exception:
                            continue
                        if lib_id_int in seen_ids:
                            continue

                        machine_ids = lib.get("machine_ids") or []
                        try:
                            machine_ids = [int(x) for x in machine_ids]
                        except Exception:
                            machine_ids = []
                        if machine_id_int not in machine_ids:
                            continue

                        if material_ids_hint:
                            lib_material_ids = lib.get("material_ids") or []
                            try:
                                lib_material_ids = [int(x) for x in lib_material_ids]
                            except Exception:
                                lib_material_ids = []
                            if not set(material_ids_hint).intersection(
                                lib_material_ids
                            ):
                                continue

                        _, extra_path = _download_tool_library_json(
                            session, lib_id_int, dest_dir=TOOLS_PATH
                        )
                        tool_library_paths.append(extra_path)
                        seen_ids.add(lib_id_int)
            except Exception:
                app.log(
                    "Failed to add fallback tool libraries:\n{}".format(
                        traceback.format_exc()
                    )
                )

        # Fetch machine name if not already set
        if machine_name is None and machine_id is not None:
            try:
                machine_name = _machine_name(session, machine_id)
            except Exception:
                app.log(
                    "Failed to fetch machine name:\n{}".format(traceback.format_exc())
                )

        if tool_library_paths:
            try:
                # Create a unique template name based on all tool_ids
                tool_ids_str = (
                    "_".join(str(tid) for tid in sorted(tool_ids))
                    if tool_ids
                    else "none"
                )
                patched_template = os.path.join(
                    TOOLS_PATH,
                    f"Plates_tool{tool_ids_str}_machine{machine_id_int}.f3dhsm-template",
                )
                patch_info = patch_cam_template_with_tool_libraries(
                    template_path,
                    patched_template,
                    tool_library_paths,
                    material_name=material_name,
                )
                if patch_info.get("missing"):
                    app.log(
                        f"Template tool matches missing: {patch_info.get('missing')}"
                    )
                template_path = patched_template
            except Exception:
                app.log(
                    "Failed to patch CAM template:\n{}".format(traceback.format_exc())
                )

        # Use true_depth from plate data if available, otherwise from payload or default
        thickness = true_depth if plate_data else float(
            _get(
                payload,
                "thickness",
                default=_get(payload, "true_depth", "trueDepth", default=0.125),
            )
        )

        SetupGenerator(
            machine_name or _get(payload, "machine"),
            true_depth,
            material_name or _get(payload, "material"),
            thickness,
            template_path=template_path,
        )
        DeleteToolpaths()

        plate_id = str(_get(payload, "plate_id", "plateId", default="cam_plate"))
        job_id = str(data.get("id", "unknown"))

        # Save the document to AutoCAM Drop folder
        try:
            # Get the AutoCAM Drop folder
            data_project = app.data.dataProjects.item(1)
            root_folder = data_project.rootFolder
            autocam_drop_folder = root_folder.dataFolders.itemByName("AutoCAM Drop")

            if autocam_drop_folder is None:
                app.log("AutoCAM Drop folder not found, creating it...")
                autocam_drop_folder = root_folder.dataFolders.add("AutoCAM Drop")

            # Save the document with Plate<plate_id>Job<job_id> format
            doc_name = f"Plate{plate_id}Job{job_id}"
            # Check if file already exists and delete it
            try:
                existing_file = autocam_drop_folder.dataFiles.itemByName(doc_name)
                if existing_file:
                    existing_file.deleteMe()
            except Exception:
                pass

            # Save the document
            doc.saveAs(doc_name, autocam_drop_folder, "", "")
            app.log(f"Saved document '{doc_name}' to AutoCAM Drop folder")

        except Exception as e:
            app.log(
                f"Failed to save document to AutoCAM Drop folder:\n{traceback.format_exc()}"
            )

        export_dir = os.path.join(FINAL_PATH, plate_id)
        try:
            shutil.rmtree(export_dir)
        except FileNotFoundError:
            pass

        export(plate_id, machine_id_int)

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
                "{BASE_URL}/api/jobs/complete",
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
        doc.close(False)
        app.log(f"Closed document '{doc_name}'")
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
            session.post(
                "{BASE_URL}/api/jobs/complete",
                files={
                    "data": (
                        None,
                        json.dumps({"error": traceback.format_exc()}),
                        "application/json",
                    )
                },
                timeout=30,
            )
