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

def edge_dir(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    line = adsk.core.Line3D.cast(edge.geometry)
    v = line.startPoint.vectorTo(line.endPoint)  # start -> end
    v.normalize()
    return v

def _linetovector(line: adsk.core.Line3D) -> adsk.core.Vector3D:
    geom = line.geometry
    start = geom.startPoint
    end = geom.endPoint
    vector = end.vectorTo(start)
    vector.normalize()
    return vector


def _angle_between_lines(line1: adsk.core.Line3D, line2: adsk.core.Line3D) -> float:
    v1 = _linetovector(line1)
    v2 = _linetovector(line2)
    angle = v1.angleTo(v2)
    angle = (angle / (2 * math.pi)) * 360
    return angle


def _lengthofline(line: adsk.core.Line3D) -> float:
    geom = line.geometry
    start = geom.startPoint
    end = geom.endPoint
    length = abs(start.distanceTo(end)) * 0.393701
    return length


def _alignEdgeToAxis(
    edge: adsk.fusion.BRepEdge,
    occ: adsk.fusion.Occurrence,
    axis: adsk.core.Vector3D,
):
    """Rotate occurrence so edge direction aligns to given axis (in world)."""
    geom: adsk.core.Line3D = edge.geometry
    start = geom.startPoint
    end = geom.endPoint
    edge_vec = end.vectorTo(start)
    edge_vec.normalize()

    # Already aligned
    if abs(edge_vec.angleTo(axis)) < 1e-3:
        return

    rot_axis = edge_vec.crossProduct(axis)
    rot_axis.normalize()
    angle = edge_vec.angleTo(axis)

    transform = adsk.core.Matrix3D.create()
    center = occ.physicalProperties.centerOfMass
    transform.setToRotation(angle, rot_axis, center)

    occ_t = occ.transform
    occ_t.transformBy(transform)
    occ.transform = occ_t


def _normalize_orientation(value):
    if value is None:
        return "vertical"
    try:
        text = str(value).strip().lower()
    except Exception:
        return "vertical"
    if text == "horizontal":
        return "horizontal"
    return "vertical"


def handleTube(template_filename: str, orientation: str = None):
    app = adsk.core.Application.get()
    ui = app.userInterface
    doc = app.activeDocument
    
    if not doc:
        ui.messageBox("No active document.")
        return

    products = doc.products
    design = adsk.fusion.Design.cast(products.itemByProductType("DesignProductType"))
    selection = design.rootComponent.occurrences.item(0)
    camWS = ui.workspaces.itemById("CAMEnvironment")
    camWS.activate()
    cam = adsk.cam.CAM.cast(products.itemByProductType("CAMProductType"))
    

    root = design.rootComponent
    if root.occurrences.count < 1:
        ui.messageBox("No occurrences found in the root component.")
        return

    # Using first occurrence (matches your add-in behavior)
    occ = root.occurrences.item(0)
    if occ.bRepBodies.count < 1:
        ui.messageBox("First occurrence has no bodies.")
        return

    body = adsk.fusion.BRepBody.cast(occ.bRepBodies.item(0))
    if not body:
        ui.messageBox("Failed to get body from the first occurrence.")
        return

    orientation_mode = _normalize_orientation(orientation)
    use_horizontal = orientation_mode == "horizontal"

    # Resolve template path relative to this script file.
    script_dir = os.path.dirname(__file__)
    template_path = os.path.join(script_dir, template_filename)
    if not os.path.exists(template_path):
        ui.messageBox(f"CAM template not found:\n{template_path}")
        return

    tubesTemplateFile = adsk.cam.CAMTemplate.createFromFile(template_path)
    tubesTemplate = adsk.cam.CreateFromCAMTemplateInput.create()
    tubesTemplate.camTemplate = tubesTemplateFile

    # ---- Identify faces / edges (your original logic) ----
    side_faces = []
    two_faces = []
    one_faces = []
    bad_faces = []
    longest_vectors = [0]

    # find 8 longest unique edges across planar faces
    for _ in range(8):
        longest_edge_length = 0
        longest_edge = None
        for face in body.faces:
            if face.geometry.objectType != adsk.core.Plane.classType():
                continue
            for edge in face.edges:
                curve = edge.geometry
                if curve.objectType != adsk.core.Line3D.classType():
                    continue
                (rv, startPoint, endPoint) = curve.evaluator.getEndPoints()
                length = abs(startPoint.distanceTo(endPoint)) * 0.393701
                if length > longest_edge_length and edge not in longest_vectors:
                    longest_edge_length = length
                    longest_edge = edge
        longest_vectors.append(longest_edge)

    facedown = None
    for face in body.faces:
        if face.geometry.objectType != adsk.core.Plane.classType():
            continue

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

                (rv, startPoint, endPoint) = curve.evaluator.getEndPoints()
                length = abs(startPoint.distanceTo(endPoint)) * 0.393701

                try:
                    inter_pt = curve.intersectWithCurve(good_edge.geometry)[0]
                except Exception:
                    continue

                is_perp = 80 < _angle_between_lines(edge, good_edge) < 100
                contains_intersection = face.boundingBox.contains(inter_pt)

                if (1.9 < length < 2.1 and face not in side_faces and face not in two_faces and is_perp and contains_intersection):
                    side_faces.append(face)
                    two_faces.append(face)
                    facedown = face
                elif (0.9 < length < 1.1 and face not in side_faces and face not in one_faces and is_perp and contains_intersection):
                    side_faces.append(face)
                    one_faces.append(face)
                elif (face not in side_faces and face not in two_faces and face not in one_faces and face not in bad_faces):
                    nowork = False
                    for face2 in side_faces:
                        if abs(app.measureManager.measureMinimumDistance(face, face2).value) < 0.1:
                            nowork = True
                            break
                    if not nowork:
                        bad_faces.append(face)

    if len(two_faces) != 2 and one_faces:
        facedown = one_faces[0]
    if not facedown:
        ui.messageBox("Could not determine a 'facedown' face. Make sure the part is a simple box tube.")
        return

    # longest edge on facedown
    longest_edge_length = 0
    longest_edge = None
    for edge in facedown.edges:
        curve = edge.geometry
        if curve.objectType != adsk.core.Line3D.classType():
            continue
        (rv, startPoint, endPoint) = curve.evaluator.getEndPoints()
        length = abs(startPoint.distanceTo(endPoint)) * 0.393701
        if length > longest_edge_length:
            longest_edge_length = length
            longest_edge = edge

    # align longest edge to +Y
    _alignEdgeToAxis(longest_edge, occ, adsk.core.Vector3D.create(0, 1, 0))

    # find perpendicular "bottom_edge" and align to +X
    bottom_edge = None
    for edge in facedown.edges:
        curve = edge.geometry
        if curve.objectType != adsk.core.Line3D.classType():
            continue
        (rv, startPoint, endPoint) = curve.evaluator.getEndPoints()
        length = abs(startPoint.distanceTo(endPoint)) * 0.393701
        if (1.5 < length < 2.5 and 80 < _angle_between_lines(edge, longest_edge) < 100):
            bottom_edge = edge
            break

    if not bottom_edge:
        ui.messageBox("Could not find perpendicular bottom edge on facedown face.")
        return

    _alignEdgeToAxis(bottom_edge, occ, adsk.core.Vector3D.create(1, 0, 0))

    # classify side faces into top/bottom and left/right based on normals
    top_bottom = []
    left_right = []
    for face in side_faces:
        n = face.geometry.normal
        n.normalize()
        nx, ny, nz = n.asArray()
        if (nz > 0.9 or nz < -0.9) and face not in top_bottom:
            top_bottom.append(face)
        elif (nx > 0.9 or nx < -0.9) and face not in left_right:
            left_right.append(face)

    if len(top_bottom) != 2 or len(left_right) != 2:
        ui.messageBox("Failed to classify tube side faces (expected 2 top/bottom and 2 left/right).")
        return

    # ordering logic (yours)
    if top_bottom[0].edges[0].geometry.startPoint.z < top_bottom[1].edges[0].geometry.startPoint.z:
        top_bottom.reverse()
    if left_right[0].edges[0].geometry.startPoint.x < left_right[1].edges[0].geometry.startPoint.x:
        left_right.reverse()


    ordered_faces = [top_bottom[0], left_right[0], top_bottom[1], left_right[1]]

    pointBox = [
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
        SetupWCSPoint.TOP_XMIN_YMIN.value,
    ]
    Xflip = [True, True, False, False]
    Yflip = [False, False, False, False]
    names = ["Top", "Right", "Bottom", "Left"]

    # ---- Build set-ups + apply template ----
    top = True
    for name1, flipX, flipY, boxPoint, face in zip(names, Xflip, Yflip, pointBox, ordered_faces):
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

        if not good_one:
            ui.messageBox(f"Could not find reference edge on face '{name1}'.")
            return

        expected_length = 2 if face in two_faces else 1 if face in one_faces else 0
        for edge in other_vectors:
            if (
                80 < _angle_between_lines(good_one, edge) < 100
                and expected_length > 0
                and expected_length - 0.1 < _lengthofline(edge) < expected_length + 0.1
            ):
                extreme_edges.append(edge)

        if not extreme_edges:
            # fallback: just pick any perpendicular edge
            for edge in other_vectors:
                if 80 < _angle_between_lines(good_one, edge) < 100:
                    extreme_edges.append(edge)
                    break

        if not extreme_edges:
            ui.messageBox(f"Could not find perpendicular edge(s) on face '{name1}'.")
            return

        if not top:
            setup.parameters.itemByName("job_stockMode").expression = "'previoussetup'"
        top = False

        setup.parameters.itemByName("job_stockOffsetMode").expression = "'all'"
        setup.parameters.itemByName("job_stockOffsetSides").expression = "0 mm"
        setup.parameters.itemByName("job_stockOffsetTop").expression = "0 mm"

        setup.parameters.itemByName("wcs_orientation_mode").value.value = "axesXY"

        axis_x_edge = good_one if use_horizontal else extreme_edges[0]
        axis_y_edge = extreme_edges[0] if use_horizontal else good_one
        setup.parameters.itemByName("wcs_orientation_axisX").value.value = [axis_x_edge]
        setup.parameters.itemByName("wcs_orientation_axisY").value.value = [axis_y_edge]

        setup.parameters.itemByName("job_model").value.value = [body]
        if name1 == "Top" or name1 == "Bottom":
            if(edge_dir(axis_x_edge).x == 1):
                flip_x_value = not flipX
            else:
                flip_x_value = flipX
            if(edge_dir(axis_y_edge).y == 1):
                flip_y_value = flipY
            else:
                flip_y_value = not flipY
        elif name1 == "Left" or name1 == "Right":
            if(edge_dir(axis_x_edge).z == 1):
                flip_x_value = flipX
            else:
                flip_x_value = not flipX
            if(edge_dir(axis_y_edge).y == 1):
                flip_y_value = flipY
            else:
                flip_y_value = not flipY
        setup.parameters.itemByName("wcs_orientation_flipY").value.value = flip_y_value
        setup.parameters.itemByName("wcs_orientation_flipX").value.value = flip_x_value

        setup.parameters.itemByName("wcs_origin_boxPoint").value.value = boxPoint

        setup.createFromCAMTemplate2(tubesTemplate)

        # post-template operation tweaks (yours)
        for operation in setup.operations:
            offset = 0.508

            if operation.strategy == "pocket2d":
                pocketSelection: adsk.cam.CadContours2dParameterValue = operation.parameters.itemByName("pockets").value
                chains: adsk.cam.CurveSelections = pocketSelection.getCurveSelections()
                chains.clear()
                chain = chains.createNewFaceContourSelection()
                chain.inputGeometry = [face]
                pocketSelection.applyCurveSelections(chains)

            if operation.strategy == "drill":
                operation.parameters.itemByName("bottomHeight_mode").value.value = "from point"

            if operation.strategy in ("drill", "pocket2d"):
                for bad_face in bad_faces:
                    n1 = bad_face.geometry.normal
                    n2 = face.geometry.normal
                    n1.normalize()
                    n2.normalize()
                    dot = n1.dotProduct(n2)
                    if (dot < -0.9) or (dot > 0.9 and bad_face.centroid.distanceTo(face.centroid) < 0.4):
                        offset = bad_face.centroid.distanceTo(face.centroid) + 0.125
                        operation.parameters.itemByName("bottomHeight_ref").value.value = [bad_face]

            elif operation.strategy == "contour2d":
                max_distance = 0
                edgeMax = None
                for edge in extreme_edges:
                    curve: adsk.core.Line3D = edge.geometry
                    if curve.objectType != adsk.core.Line3D.classType():
                        continue
                    p_end = curve.evaluator.getParameterAtPoint(curve.endPoint)[1]
                    p_start = curve.evaluator.getParameterAtPoint(curve.startPoint)[1]
                    p = p_end if p_end > p_start else p_start
                    if p > max_distance:
                        max_distance = p
                        edgeMax = edge

                if edgeMax:
                    parameter: adsk.cam.CadContours2dParameterValue = operation.parameters.itemByName("contours").value
                    selection: adsk.cam.CurveSelections = parameter.getCurveSelections()
                    selection.clear()
                    chain = selection.createNewChainSelection()
                    chain.isOpen = True
                    chain.isReverted = True if name1 in ("Top", "Right") else False
                    chain.inputGeometry = [edgeMax]
                    parameter.applyCurveSelections(selection)

                operation.parameters.itemByName("bottomHeight_mode").value.value = "from stock top"
                operation.parameters.itemByName("bottomHeight_offset").expression = f"-{offset} cm"

    cam.generateAllToolpaths(skipValid=False)
