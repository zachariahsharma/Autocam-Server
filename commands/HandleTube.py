import adsk.core, adsk.fusion, adsk.cam, traceback
from enum import Enum
import math
import os
import time


class SetupWCSPoint(Enum):
    TOP_CENTER = "top center"
    TOP_XMIN_YMIN = "top 1"
    TOP_XMAX_YMIN = "top 2"
    TOP_XMIN_YMAX = "top 3"
    TOP_XMAX_YMAX = "top 4"
    TOP_SIDE_YMIN = "top side 1"
    TOP_SIDE_XMAX = "top side 2"
    TOP_SIDE_YMAX = "top side 3"
    TOP_SIDE_XMIN = "top side 4"
    CENTER = "center"
    MIDDLE_XMIN_YMIN = "middle 1"
    MIDDLE_XMAX_YMIN = "middle 2"
    MIDDLE_XMIN_YMAX = "middle 3"
    MIDDLE_XMAX_YMAX = "middle 4"
    MIDDLE_SIDE_YMIN = "middle side 1"
    MIDDLE_SIDE_XMAX = "middle side 2"
    MIDDLE_SIDE_YMAX = "middle side 3"
    MIDDLE_SIDE_XMIN = "middle side 4"
    BOTTOM_CENTER = "bottom center"
    BOTTOM_XMIN_YMIN = "bottom 1"
    BOTTOM_XMAX_YMIN = "bottom 2"
    BOTTOM_XMIN_YMAX = "bottom 3"
    BOTTOM_XMAX_YMAX = "bottom 4"
    BOTTOM_SIDE_YMIN = "bottom side 1"
    BOTTOM_SIDE_XMAX = "bottom side 2"
    BOTTOM_SIDE_YMAX = "bottom side 3"
    BOTTOM_SIDE_XMIN = "bottom side 4"


def linetovector(line: adsk.core.Line3D) -> adsk.core.Vector3D:
    geom = line.geometry
    start = geom.startPoint
    end = geom.endPoint
    vector = end.vectorTo(start)
    vector.normalize()
    return vector


def angle_between_lines(line1: adsk.core.Line3D, line2: adsk.core.Line3D) -> float:
    v1 = linetovector(line1)
    v2 = linetovector(line2)
    angle = v1.angleTo(v2)
    angle = (angle / (2 * math.pi)) * 360
    return angle


def lengthofline(line: adsk.core.Line3D) -> float:
    geom = line.geometry
    start = geom.startPoint
    end = geom.endPoint
    length = abs(start.distanceTo(end)) * 0.393701
    return length


def alignEdgeToYAxis(
    edge: adsk.fusion.BRepEdge,
    bodyOcc: adsk.fusion.Occurrence,
    axis: adsk.core.Vector3D = None,
):
    # 1. Get edge direction vector
    geom: adsk.core.Line3D = edge.geometry
    start = geom.startPoint
    end = geom.endPoint
    edgeVector = end.vectorTo(start)
    edgeVector.normalize()

    # If already aligned (parallel)
    if abs(edgeVector.angleTo(axis)) < 1e-3:
        return

    # 3. Rotation axis = cross product
    rotAxis = edgeVector.crossProduct(axis)
    rotAxis.normalize()

    # 4. Rotation angle
    angle = edgeVector.angleTo(axis)

    # 5. Rotation matrix about body’s center
    transform = adsk.core.Matrix3D.create()
    center = bodyOcc.physicalProperties.centerOfMass
    transform.setToRotation(angle, rotAxis, center)
    occTransform = bodyOcc.transform
    occTransform.transformBy(transform)
    bodyOcc.transform = occTransform


def handleTube():
    app = adsk.core.Application.get()
    ui = app.userInterface
    doc = app.activeDocument
    products = doc.products
    design = adsk.fusion.Design.cast(products.itemByProductType("DesignProductType"))
    selection = design.rootComponent.occurrences.item(0)
    camWS = ui.workspaces.itemById("CAMEnvironment")
    camWS.activate()
    cam = adsk.cam.CAM.cast(products.itemByProductType("CAMProductType"))

    # Select the box tube component
    body = adsk.fusion.BRepBody.cast(selection.entity)
    # Identify the four side faces
    side_faces = []
    two_faces = []
    one_faces = []
    bad_faces = []
    longest_vectors = [0]
    for i in range(8):
        longest_edge_length = 0
        longest_edge = None
        for face in body.faces:
            if face.geometry.objectType == adsk.core.Plane.classType():
                face: adsk.core.Plane
                for edge in face.edges:
                    curve = edge.geometry
                    if curve.objectType != adsk.core.Line3D.classType():
                        continue
                    (returnValue, startPoint, endPoint) = curve.evaluator.getEndPoints()
                    length = abs(startPoint.distanceTo(endPoint)) * 0.393701
                    if length > longest_edge_length and edge not in longest_vectors:
                        longest_edge_length = length
                        longest_edge = edge
        longest_vectors.append(longest_edge)
    facedown = None
    for face in body.faces:
        if face.geometry.objectType == adsk.core.Plane.classType():
            face: adsk.core.Plane
            edge_count = 0
            good_edge = None
            for edge in face.edges:
                if edge in longest_vectors:
                    edge_count += 1
                    good_edge = edge
            if edge_count > 1:
                for edge in face.edges:
                    curve = edge.geometry
                    if curve.objectType != adsk.core.Line3D.classType():
                        continue
                    (returnValue, startPoint, endPoint) = curve.evaluator.getEndPoints()
                    length = abs(startPoint.distanceTo(endPoint)) * 0.393701
                    # app.log(str(length))
                    if (
                        length > 1.9
                        and length < 2.1
                        and face not in side_faces
                        and face not in two_faces
                        and angle_between_lines(edge, good_edge) > 80
                        and angle_between_lines(edge, good_edge) < 100
                        and face.boundingBox.contains(
                            curve.intersectWithCurve(good_edge.geometry)[0]
                        )
                    ):
                        side_faces.append(face)
                        two_faces.append(face)
                        facedown = face
                    elif (
                        length < 1.1
                        and length > 0.9
                        and face not in side_faces
                        and face not in one_faces
                        and angle_between_lines(edge, good_edge) > 80
                        and angle_between_lines(edge, good_edge) < 100
                        and face.boundingBox.contains(
                            curve.intersectWithCurve(good_edge.geometry)[0]
                        )
                    ):
                        side_faces.append(face)
                        one_faces.append(face)
                    elif (
                        face not in side_faces
                        and face not in two_faces
                        and face not in one_faces
                        and face not in bad_faces
                    ):
                        nowork = False
                        for face2 in side_faces:
                            if (
                                abs(
                                    app.measureManager.measureMinimumDistance(
                                        face, face2
                                    ).value
                                )
                                < 0.1
                            ):
                                nowork = True
                        if not nowork:
                            # app.log("length: " + str(length))
                            bad_faces.append(face)
    if len(two_faces) != 2:
        facedown = one_faces[0]
    longest_edge_length = 0
    longest_edge = None
    for edge in facedown.edges:
        curve = edge.geometry
        if curve.objectType != adsk.core.Line3D.classType():
            continue
        (returnValue, startPoint, endPoint) = curve.evaluator.getEndPoints()
        length = abs(startPoint.distanceTo(endPoint)) * 0.393701
        if length > longest_edge_length:
            longest_edge_length = length
            longest_edge = edge
    alignEdgeToYAxis(
        longest_edge,
        design.rootComponent.occurrences.item(0),
        adsk.core.Vector3D.create(0, 1, 0),
    )
    bottom_edge = None
    for edge in facedown.edges:
        curve = edge.geometry
        if curve.objectType != adsk.core.Line3D.classType():
            continue
        (returnValue, startPoint, endPoint) = curve.evaluator.getEndPoints()
        length = abs(startPoint.distanceTo(endPoint)) * 0.393701
        if (
            length > 1.5
            and length < 2.5
            and angle_between_lines(edge, longest_edge) > 80
            and angle_between_lines(edge, longest_edge) < 100
        ):
            bottom_edge = edge
    alignEdgeToYAxis(
        bottom_edge,
        design.rootComponent.occurrences.item(0),
        adsk.core.Vector3D.create(1, 0, 0),
    )
    top_bottom = []
    left_right = []
    for face in side_faces:
        normal = face.geometry.normal
        normal.normalize()
        normal = normal.asArray()
        if normal[2] > 0.9 or normal[2] < -0.9 and face not in top_bottom:
            top_bottom.append(face)
        elif normal[0] > 0.9 or normal[0] < -0.9 and face not in left_right:
            left_right.append(face)
    side_faces = []
    if (
        top_bottom[0].edges[0].geometry.startPoint.z
        < top_bottom[1].edges[0].geometry.startPoint.z
    ):
        top_bottom.reverse()
    if (
        left_right[0].edges[0].geometry.startPoint.x
        < left_right[1].edges[0].geometry.startPoint.x
    ):
        left_right.reverse()
    side_faces.append(top_bottom[0])
    side_faces.append(left_right[0])
    side_faces.append(top_bottom[1])
    side_faces.append(left_right[1])
    pointBox = [
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
    ]
    Xflip = [True, True, False, False]
    Yflip = [True, True, True, True]
    name = ["Top", "Right", "Bottom", "Left"]
    tubesTemplateFile = adsk.cam.CAMTemplate.createFromFile(
        os.path.join(os.path.dirname(__file__), "../templates/Tubes.f3dhsm-template")
    )
    tubesTemplate = adsk.cam.CreateFromCAMTemplateInput.create()
    tubesTemplate.camTemplate = tubesTemplateFile
    top = True
    for name1, flipX, flipY, boxPoint, (i, face) in zip(
        name, Xflip, Yflip, pointBox, enumerate(side_faces)
    ):
        setupInput = cam.setups.createInput(0)
        setupInput.name = name1
        setup = cam.setups.add(setupInput)
        setup.stockMode = adsk.cam.SetupStockModes.RelativeBoxStock
        good_one = None
        other_vectors = []
        extreme_edges = []
        for edge in face.edges:
            curve = edge.geometry
            if curve.objectType != adsk.core.Line3D.classType():
                continue
            if edge in longest_vectors:
                good_one = edge
            else:
                other_vectors.append(edge)
        expected_length = 2 if face in two_faces else 1 if face in one_faces else 0
        for edge in other_vectors:
            if (
                angle_between_lines(good_one, edge) < 100
                and angle_between_lines(good_one, edge) > 80
                and lengthofline(edge) > expected_length - 0.1
                and lengthofline(edge) < expected_length + 0.1
            ):
                extreme_edges.append(edge)
        if not top:
            setup.parameters.itemByName("job_stockMode").expression = "'previoussetup'"
        top = False
        setup.parameters.itemByName("job_stockOffsetMode").expression = "'all'"
        setup.parameters.itemByName("job_stockOffsetSides").expression = "0 mm"
        setup.parameters.itemByName("job_stockOffsetTop").expression = "0 mm"
        setup.parameters.itemByName("wcs_orientation_mode").value.value = "axesXY"
        setup.parameters.itemByName("wcs_orientation_axisX").value.value = [
            extreme_edges[0]
        ]
        setup.parameters.itemByName("wcs_orientation_axisY").value.value = [good_one]
        setup.parameters.itemByName("job_model").value.value = [body]
        setup.parameters.itemByName("wcs_orientation_flipY").value.value = flipY
        setup.parameters.itemByName("wcs_orientation_flipX").value.value = flipX
        setup.parameters.itemByName("wcs_origin_boxPoint").value.value = boxPoint
        setup.createFromCAMTemplate2(tubesTemplate)
        for operation in setup.operations:
            offset = 0.508
            if operation.strategy == "pocket2d":
                pocketSelection: adsk.cam.CadContours2dParameterValue = (
                    operation.parameters.itemByName("pockets").value
                )
                chains: adsk.cam.CurveSelections = pocketSelection.getCurveSelections()
                chains.clear()
                chain = chains.createNewFaceContourSelection()
                chain.inputGeometry = [face]
                pocketSelection.applyCurveSelections(chains)
            if operation.strategy == "drill":
                operation.parameters.itemByName("bottomHeight_mode").value.value = (
                    "from point"
                )
            if operation.strategy == "drill" or operation.strategy == "pocket2d":
                for bad_face in bad_faces:
                    normal1 = bad_face.geometry.normal
                    normal2 = face.geometry.normal
                    normal1.normalize()
                    normal2.normalize()
                    dot_product = normal1.dotProduct(normal2)
                    # if app.measureManager.measureMinimumDistance(bad_face[0], face[0]).value < 0.003175:
                    if (
                        dot_product < -0.9
                        or dot_product > 0.9
                        and bad_face.centroid.distanceTo(face.centroid) < 0.4
                    ):
                        offset = bad_face.centroid.distanceTo(face.centroid) + 0.125
                        operation.parameters.itemByName(
                            "bottomHeight_ref"
                        ).value.value = [bad_face]
            elif operation.strategy == "contour2d":
                max_distance = 0
                edgeMax = None
                for edge in extreme_edges:
                    curve: adsk.core.Line3D = edge.geometry
                    if curve.objectType != adsk.core.Line3D.classType():
                        continue
                    if (
                        curve.evaluator.getParameterAtPoint(curve.endPoint)[1]
                        > max_distance
                    ):
                        max_distance = (
                            curve.evaluator.getParameterAtPoint(curve.endPoint)[1]
                            if curve.evaluator.getParameterAtPoint(curve.endPoint)[1]
                            > curve.evaluator.getParameterAtPoint(curve.startPoint)[1]
                            else curve.evaluator.getParameterAtPoint(curve.startPoint)[
                                1
                            ]
                        )
                        edgeMax = edge
                parameter: adsk.cam.CadContours2dParameterValue = (
                    operation.parameters.itemByName("contours").value
                )
                selection: adsk.cam.CurveSelections = parameter.getCurveSelections()
                selection.clear()
                chain = selection.createNewChainSelection()
                chain.isOpen = True
                if name1 == "Top" or name1 == "Right":
                    chain.isReverted = True
                else:
                    chain.isReverted = False
                chain.inputGeometry = [edgeMax]
                parameter.applyCurveSelections(selection)
                operation.parameters.itemByName("bottomHeight_mode").value.value = (
                    "from stock top"
                )
                operation.parameters.itemByName("bottomHeight_offset").expression = (
                    f"-{offset} cm"
                )
    cam.generateAllToolpaths(skipValid=False)
