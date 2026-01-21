# Author-
# Description-
import adsk.core, adsk.fusion, adsk.cam, traceback
from ..config import *
import os
import json
import re
import time


def get_tool_diameter(toolpath):
    """Get tool diameter in inches from a toolpath"""
    try:
        value = toolpath.tool.parameters.itemByName("tool_diameter").value
        return value.value / 2.54  # Convert from cm to inches
    except Exception:
        return 0


def _format_tool_label(toolpath):
    """Create a filename-friendly label from the tool diameter."""
    try:
        value = toolpath.tool.parameters.itemByName("tool_diameter").value.value
    except Exception:
        return "0"
    inches = value / 2.54
    numbers_only = re.sub(r"[^0-9]", "", str(inches))
    if not numbers_only:
        numbers_only = "0"
    try:
        formatted = f"{float(numbers_only):3.2f}"
    except Exception:
        formatted = numbers_only
    label = formatted.replace(".", "").strip("0")
    return label or "0"


def export(name, machine):
    ui = None
    app = adsk.core.Application.get()
    ui = app.userInterface
    design = app.activeProduct

    # Ensure we are in the CAM workspace
    cam = adsk.cam.CAM.cast(design)
    allSetups = cam.setups
    absolutePath = os.path.join(TOOLS_PATH, f"machine_{machine}.cps")
    folder_path = os.path.join(FINAL_PATH, name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    for setup in allSetups:
        releventToolpaths = {
            "Drills": [],
            "Pocket": [],
            "Profile": [],
        }
        for toolpath in setup.operations:
            if toolpath.name == "Suppress":
                continue
            if toolpath.strategy == "drill":
                releventToolpaths["Drills"].append(toolpath)
            elif toolpath.strategy == "pocket_clearing":
                releventToolpaths["Pocket"].append(toolpath)
            else:
                releventToolpaths["Profile"].append(toolpath)

        # Sort drills by diameter ascending (smallest first)
        releventToolpaths["Drills"].sort(key=get_tool_diameter)
        # Sort pockets by diameter descending (largest first)
        releventToolpaths["Pocket"].sort(key=get_tool_diameter, reverse=True)

        for toolpath in releventToolpaths["Drills"]:
            postProcessInput = adsk.cam.PostProcessInput.create(
                setup.name[0] + str(toolpath.name).split(" ")[0],
                absolutePath,
                folder_path,
                adsk.cam.PostOutputUnitOptions.MillimetersOutput,
            )
            postProcessInput.isOpenInEditor = False
            cam.postProcess(toolpath, postProcessInput)
        for toolpath in releventToolpaths["Pocket"]:
            tool = _format_tool_label(toolpath)
            postProcessInput = adsk.cam.PostProcessInput.create(
                setup.name[0] + tool + "Pocket",
                absolutePath,
                folder_path,
                adsk.cam.PostOutputUnitOptions.MillimetersOutput,
            )
            postProcessInput.isOpenInEditor = False
            try:
                cam.postProcess(toolpath, postProcessInput)
            except Exception:
                app.log(
                    "Failed to post process pocket toolpath:\n{}".format(
                        traceback.format_exc()
                    )
                )

        for toolpath in releventToolpaths["Profile"]:
            tool = _format_tool_label(toolpath)
            postProcessInput = adsk.cam.PostProcessInput.create(
                setup.name[0] + tool + "Profile",
                absolutePath,
                folder_path,
                adsk.cam.PostOutputUnitOptions.MillimetersOutput,
            )
            postProcessInput.isOpenInEditor = False
            cam.postProcess(
                toolpath,
                postProcessInput,
            )
