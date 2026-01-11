import adsk.core, adsk.fusion, adsk.cam, traceback

import json
import os
import shutil
import time

import requests
from typing import Optional

from ..commands.MultiImport import importFiles
from ..commands.NewNCProgram import export
from ..commands.DeleteToolpaths import DeleteToolpaths
from ..commands.HandleTube import handleTube
from ..config import FINAL_PATH, INITIAL_PATH, TEMP_PATH, TOOLS_PATH
from .templateTools import patch_cam_template_with_tool_libraries


def _get(payload: dict, *keys: str, default=None):
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _download_tool_library_json(
    session: requests.Session, tool_id: int, dest_dir: str
) -> tuple[dict, str]:
    os.makedirs(dest_dir, exist_ok=True)
    resp = session.get(f"http://localhost:3000/api/tools/{tool_id}", timeout=30)
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

    resp = session.get("http://localhost:3000/api/materials", timeout=30)
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

    resp = session.get("http://localhost:3000/api/machines", timeout=30)
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
    resp = session.get(f"http://localhost:3000/api/machines/{machine_id}", timeout=30)
    resp.raise_for_status()
    info = resp.json()
    if not isinstance(info, dict):
        raise TypeError(f"Unexpected machine response: {type(info)}")

    url = info.get("file")
    if not url:
        raise ValueError("Machine response missing 'file' signed URL")

    file_ext = ".cps"
    out_path = os.path.join(dest_dir, f"machine_{machine_id}{file_ext}")
    if not os.path.exists(out_path):
        content = requests.get(url, timeout=30).content
        with open(out_path, "wb") as f:
            f.write(content)

    return info, out_path


def _download_box_tube_file(
    session: requests.Session, tube_id: int, dest_dir: str
) -> str:
    """Download a box tube STEP file from the API and save it locally."""
    os.makedirs(dest_dir, exist_ok=True)
    app = adsk.core.Application.get()
    resp = session.get(f"http://localhost:3000/api/boxTubes/{tube_id}", timeout=30)
    resp.raise_for_status()
    info = resp.json()
    if not isinstance(info, dict):
        raise TypeError(f"Unexpected box tube response: {type(info)}")

    url = info.get("file")
    if not url:
        raise ValueError("Box tube response missing 'file' signed URL")
    app.log(f"Downloading box tube STEP file from URL: {url}")
    out_path = os.path.join(dest_dir, f"{tube_id}.step")
    if not os.path.exists(out_path):
        content = requests.get(url, timeout=30).content
        with open(out_path, "wb") as f:
            f.write(content)

    return out_path


def start(data, session):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        app.log("Starting box tube CAM workflow...")
        app.log(f"Job data: {json.dumps(data)}")

        # Expect payload to follow BoxTubePayload schema
        payload = data.get("payload") or {}
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


        # Single box tube per payload
        box_tube_id = _get(payload, "box_tube_id")
        if box_tube_id is None:
            raise ValueError("Payload missing required 'box_tube_id'")
        try:
            box_tube_id_int = int(box_tube_id)
        except Exception:
            raise ValueError(f"Invalid box_tube_id: {box_tube_id}")

        # Download STEP file from API
        try:
            _download_box_tube_file(session, box_tube_id_int, INITIAL_PATH)
        except Exception:
            app.log("Failed to download box tube file:\n{}".format(traceback.format_exc()))
            raise

        # Import the single tube
        importFiles(
            [os.path.join(INITIAL_PATH, f"{box_tube_id_int}.step")],
            [1],
        )

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
            os.path.dirname(__file__), "../templates/boxtubes.f3dhsm-template"
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
                resp = session.get("http://localhost:3000/api/tools", timeout=30)
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
                    f"Boxtubes_tool{tool_ids_str}_machine{machine_id_int}.f3dhsm-template",
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

        handleTube(patched_template)
        DeleteToolpaths()
        
        box_tube_id = str(_get(payload, "box_tube_id", default="cam_tube"))
        job_id = str(data.get("id", "unknown"))
        doc_name = f"Tube{box_tube_id}Job{job_id}"

        # Save the document to AutoCAM Drop folder
        try:
            # Get the AutoCAM Drop folder
            data_project = app.data.dataProjects.item(1)
            root_folder = data_project.rootFolder
            autocam_drop_folder = root_folder.dataFolders.itemByName("AutoCAM Drop")

            if autocam_drop_folder is None:
                app.log("AutoCAM Drop folder not found, creating it...")
                autocam_drop_folder = root_folder.dataFolders.add("AutoCAM Drop")

            # Save the document with Tube<tube_id>Job<job_id> format
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

        export_dir = os.path.join(FINAL_PATH, box_tube_id)
        try:
            shutil.rmtree(export_dir)
        except FileNotFoundError:
            pass

        export(box_tube_id, machine_id_int)

        zip_base = os.path.join(FINAL_PATH, box_tube_id)
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
                        f"{box_tube_id}.zip",
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
