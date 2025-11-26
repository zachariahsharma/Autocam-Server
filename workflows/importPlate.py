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
import numpy as np
import requests


def start(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        excess = {}
        screnshots = {}
        for i, plate in enumerate(context["plates"]):
            doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            importFiles(
                [
                    STEPBASEPATH + child["id"] + ".step"
                    for child in context["plateParts"][i]["parts"]
                ],
                [child["quantity"] for child in context["plateParts"][i]["parts"]],
            )
            comp: adsk.fusion.Component = app.activeProduct.rootComponent
            for occ in comp.allOccurrences:
                res = orient_plate_pocket_side_up(occ)
                # app.log(f"Orientned {occ.name}: {res}")
            arrange = AutoArrange(plate["Length"], plate["Width"])
            occurances = []
            for envelope in arrange.resultEnvelopes:
                app.log(f"Arranging envelope {envelope.name}")
                if "Envelope1" not in envelope.name:
                    for occ in envelope.occurrences:
                        occurances.append(
                            occ.occurrence.bRepBodies.item(0).parentComponent.name
                        )
            occurances = [str(x).split(" ")[0] for x in occurances]
            occurances, quantity = np.unique(occurances, return_counts=True)
            excess[context["plateParts"][i]["plateId"]] = {
                "occurances": occurances.tolist(),
                "quantity": quantity.tolist(),
            }
            screenshotEnvelope(
                plate["Width"], plate["Length"], context["plateParts"][i]["plateId"]
            )
            screnshots[context["plateParts"][i]["plateId"]] = (
                os.path.join(os.path.dirname(os.path.realpath(__file__)), "../temp")
                + "/"
                + context["plateParts"][i]["plateId"]
                + ".png"
            )
            doc.close(False)
        app.log("EXCESSSSSSS: " + str(excess))
        app.log("hello")
        # headers = {
        #     "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36",
        #     "Content-Type": "application/json",
        # }

        opened_files = []
        try:
            files_payload = []
            for plate_id, path in screnshots.items():
                f = open(path, "rb")
                opened_files.append(f)
                files_payload.append(
                    ("screenshots", (f"{plate_id}.png", f, "image/png"))
                )
            data = {"json": json.dumps(excess)}
            x = requests.post(
                "http://127.0.0.1:5000/mt/webhook/not_fit",
                # headers=headers,
                data=data,
                files=files_payload,
                timeout=30,
            )
        except Exception as e:
            app.log("Error during request: " + str(e))
            raise e
        finally:
            for f in opened_files:
                try:
                    f.close()
                except:
                    pass
        for screenshot in screnshots.values():
            try:
                os.remove(screenshot)
            except:
                pass
        app.log(str(x.status_code) + " " + x.reason)
        # app.log(x.text)
    except:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
