import os
from ..config import *
import sys
import requests
import adsk.core

sys.path.append(OVERRIDE_PATH)


def setupTempDir():
    for path in (TEMP_PATH, INITIAL_PATH, FINAL_PATH, TOOLS_PATH):
        if not os.path.exists(path):
            os.makedirs(path)
    return TEMP_PATH


def downloadFiles(temp_dir, data, session):
    for part in data["payload"]["assignments"]:
        partsData = session.get(f"{BASE_URL}/api/parts/{part['part_id']}")
        if partsData.status_code != 200:
            app = adsk.core.Application.get()
            app.log("Error fetching part data: " + str(partsData.json()))
            continue
        app = adsk.core.Application.get()
        app.log(str(partsData.json()))
        with open(
            os.path.join(temp_dir, "initial", f"{part['part_id']}.step"), "wb"
        ) as f:
            f.write(requests.get(partsData.json()["file"]).content)
