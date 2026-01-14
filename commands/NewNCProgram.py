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
    except:
        return 0


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
            value: adsk.cam.CadObjectParameterValue = (
                toolpath.tool.parameters.itemByName("tool_diameter").value
            )
            value = value.value / 2.54
            numbers_only = re.sub(
                r"[^0-9]",
                "",
                str(value),
            )
            tool = f"{float(numbers_only):3.2f}".replace(".", "").strip("0")
            camManager = adsk.cam.CAMManager.get()
            libraryManager: adsk.cam.CAMLibraryManager = camManager.libraryManager
            postLibrary: adsk.cam.PostLibrary = libraryManager.postLibrary

            postQuery: adsk.cam.PostConfigurationQuery = postLibrary.createQuery(
                adsk.cam.LibraryLocations.CloudLibraryLocation
            )
            postQuery.capability = adsk.cam.PostCapabilities.Milling
            postConfigs: list[adsk.cam.PostConfiguration] = postQuery.execute()

            # Find the "XYZ" post in the post library and import it to local library
            postconfig = [pc for pc in postConfigs if pc.description == "Laguna CNC"][0]

            ncInput: adsk.cam.NCProgramInput = cam.ncPrograms.createInput()
            ncInput.displayName = setup.name[0] + tool + "Pocket"
            ncParameters: adsk.cam.CAMParameters = ncInput.parameters
            ncParameters.itemByName("nc_program_filename").value.value = (
                setup.name[0] + tool + "Pocket"
            )
            ncParameters.itemByName("nc_program_openInEditor").value.value = False
            ncParameters.itemByName("nc_program_output_folder").value.value = (
                folder_path
            )
            ncInput.operations = [toolpath]
            newProgram: adsk.cam.NCProgram = cam.ncPrograms.add(ncInput)
            newProgram.postConfiguration = postconfig
            postParameters: adsk.cam.CAMParameters = newProgram.postParameters
            newProgram.updatePostParameters(postParameters)
            postOptions = adsk.cam.NCProgramPostProcessOptions.create()
            try:
                newProgram.postProcess(postOptions)
            except:
                continue
            app.log(f"Exported")

        for toolpath in releventToolpaths["Profile"]:
            value: adsk.cam.CadObjectParameterValue = (
                toolpath.tool.parameters.itemByName("tool_diameter").value
            )
            value = value.value / 2.54
            numbers_only = re.sub(
                r"[^0-9]",
                "",
                str(value),
            )
            tool = f"{float(numbers_only):3.2f}".replace(".", "").strip("0")
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
