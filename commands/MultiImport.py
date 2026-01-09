# Created by Portland CNC
# URL: https://pdxcnc.com

import adsk.core, adsk.fusion, traceback
import os


def importFiles(filenames, quantities):
    app = adsk.core.Application.get()
    app.log(str(filenames))
    ui = app.userInterface
    design = app.activeProduct
    rootComp = design.rootComponent
    for filename, quantity in zip(filenames, quantities):
        componentName = os.path.splitext(os.path.basename(filename))[0]
        importOptions = app.importManager.createSTEPImportOptions(filename)
        quantity = int(quantity)
        for _ in range(quantity):
            app.importManager.importToTarget(importOptions, rootComp)
            lastOcc = rootComp.occurrences[-1]
            lastOcc.component.name = componentName