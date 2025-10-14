import adsk.core, adsk.fusion, adsk.cam, traceback


def orient_plate_pocket_side_up(occurrence: adsk.fusion.Occurrence):
    largestFace = 0
    app = adsk.core.Application.get()
    for face in occurrence.bRepBodies.item(0).faces:
        if face.area > largestFace:
            try:
                normal = face.geometry.normal
                largestFace = face.area
            except:
                continue
    transform = occurrence.transform2
    app.log("transform: " + str(transform))
    n_world = normal.copy()
    n_world.transformBy(occurrence.transform2)
    n_world.normalize()
    target = adsk.core.Vector3D.create(0, 0, 1)
    angle = n_world.angleTo(target)
    if angle < 1e-8:
        app.log("No rotation needed")
        return
    axis = n_world.crossProduct(target)
    if axis.length < 1e-8:
        axis = adsk.core.Vector3D.create(1, 0, 0)
        if abs(axis.dotProduct(target)) > 0.99:
            axis = adsk.core.Vector3D.create(0, 1, 0)
    axis.normalize()
    R = adsk.core.Matrix3D.create()
    R.setToRotation(angle, axis, adsk.core.Point3D.create(0, 0, 0))
    comp = occurrence.component
    moveFeats = comp.features.moveFeatures
    objs = adsk.core.ObjectCollection.create()
    for b in comp.bRepBodies:
        objs.add(b)

    mi = moveFeats.createInput(objs, R)  # <-- required transform argument
    moveFeats.add(mi)
