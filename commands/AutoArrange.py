import traceback
import adsk.core
import adsk.fusion


def AutoArrange(length, width) -> adsk.fusion.ArrangeFeature:
    app = adsk.core.Application.get()
    ui = app.userInterface
    des: adsk.fusion.Design = app.activeProduct
    comp = des.rootComponent
    arrangeFeats = comp.features.arrangeFeatures

    # Create the input.
    arrangeInput: adsk.fusion.ArrangeFeatureInput = arrangeFeats.createInput(
        adsk.fusion.ArrangeSolverTypes.Arrange2DTrueShapeSolverType
    )

    # Get the definition object from the input.
    arrangeDefInput: adsk.fusion.ArrangeDefinition2DInput = arrangeInput.definition

    # Modify some of the arrange settings.
    arrangeDefInput.globalRotation = (
        adsk.fusion.ArrangeRotationTypes.NoneArrangeRotationType
    )
    arrangeDefInput.isGlobalDirectionFaceUp = False
    arrangeDefInput.isPartInPartAllowed = True
    arrangeDefInput.isCreateCopies = False
    # Get the ArrangeComponents collection from the input objects.
    arrComponents = arrangeInput.arrangeComponents

    # Get the occurrences to arrange.
    occ1 = list(comp.allOccurrences)
    for occ in occ1:
        occ.isGrounded = False
        occ.isGroundToParent = False
        # largestArea = 0
        # for face in occ.bRepBodies.item(0).faces:
        #     if face.area > largestArea:
        #         largestArea = face.area
        #         normal = face.geometry.normal
        # app.log(str(normal.asArray()))
        arrComponents.add(occ)
        # arrcomp.upDirection = adsk.core.Vector3D.create(0, 0, -1)
    # return
    # Define a plane envelope.
    app.log(f"Length: {length}, Width: {width}")
    planeEnv = arrangeInput.setPlaneEnvelope(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString(f"{length} in"),
        adsk.core.ValueInput.createByString(f"{width} in"),
    )

    # Modify some additional properties of the envelope.
    planeEnv.originXOffset = adsk.core.ValueInput.createByString("40 cm")
    planeEnv.originYOffset = adsk.core.ValueInput.createByString("0 cm")
    planeEnv.quantity = adsk.core.ValueInput.createByString("-1")
    planeEnv.objectSpacing = adsk.core.ValueInput.createByString(".26 in")
    planeEnv.envelopeSpacing = adsk.core.ValueInput.createByString("0.5 in")
    planeEnv.frameWidth = adsk.core.ValueInput.createByString("0.5 in")

    # Create the arrange feature.
    arrange = arrangeFeats.add(arrangeInput)
    topFace = 0
    bottomFace = 0
    for occ in occ1:
        for face in occ.bRepBodies.item(0).faces:
            try:
                if face.geometry.normal.z > 0.9:
                    topFace += face.area
                if face.geometry.normal.z < -0.9:
                    bottomFace += face.area
            except:
                continue
    if bottomFace > topFace:
        arrange.deleteMe()
        planeEnv.isFlipped = True
        arrange = arrangeFeats.add(arrangeInput)
    return arrange
