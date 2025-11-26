import adsk.core, adsk.fusion, adsk.cam, traceback

import os
from ..commands.SetupGenerator import SetupGenerator
from ..commands.MultiImport import importFiles
from ..commands.NewNCProgram import export
from ..commands.DeleteToolpaths import DeleteToolpaths
from ..commands.AutoArrange import AutoArrange
from ..config import *
import sys

sys.path.append(OVERRIDE_PATH)
import shutil
import requests


def start(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        app = adsk.core.Application.get()
        ui: adsk.core.UserInterface = app.userInterface
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        importFiles(
            [STEPBASEPATH + child["name"] + ".step" for child in context["parts"]],
            [child["quantity"] for child in context["parts"]],
        )
        AutoArrange(context["length"], context["width"])
        SetupGenerator(
            context["machine"],
            float(context["trueDepth"]),
            context["material"],
            float(context["thickness"]),
        )
        DeleteToolpaths()
        # raise Exception("Debug Stop")
        export(context["parts"][0]["name"])
        app.activeDocument.saveAs(
            context["parts"][0]["name"],
            app.data.activeProject.rootFolder.dataFolders.itemByName(
                "2025 Robot"
            ).dataFolders.itemByName("AutoCAMDrop"),
            context["parts"][0]["name"],
            "AutoCAM",
        )
        shutil.make_archive(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                f"../temp/{context['parts'][0]['name']}",
            ),
            "zip",
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                f"../temp/{context['parts'][0]['name']}",
            ),
        )
        shutil.rmtree(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                f"../temp/{context['parts'][0]['name']}",
            )
        )
        requests.post(
            "http://127.0.0.1:5000/mt/webhook/cam_bundle",
            data={"plateId": context["plateId"]},
            files={
                "file": open(
                    os.path.join(
                        os.path.dirname(os.path.realpath(__file__)),
                        f"../temp/{context['parts'][0]['name']}.zip",
                    ),
                    "rb",
                )
            },
        )
        os.remove(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                f"../temp/{context['parts'][0]['name']}.zip",
            )
        )
        app.log("hello")
        app.activeDocument.close(False)

    except Exception as e:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
