"""
ar_glasses_pod_v0.py — two-piece clip-on pod for a Wayfarer-style temple arm.

Modelled after BasedHardware OpenGlass's clip-on approach, scaled down.
Rail-slide friction clip (no hinge in the dupes = slide pod on from the ear end).
Body holds XIAO ESP32-S3 Sense + 300mAh LiPo + MAX98357A amp, stacked vertically.
Lid friction-fits into a rabbet on the bottom of the body (no snap tabs in v0).

Run headless:
    blender --background --python ar_glasses_pod_v0.py

Outputs next to this script:
    ar_glasses_pod_v0_body.stl
    ar_glasses_pod_v0_lid.stl

Coordinates:
  +X = length along temple  (0 = hinge end / front, POD_L = ear end / back)
  +Y = width across temple  (0 = centerline, +Y = outer side, away from face)
  +Z = vertical             (0 = bottom / lid side, POD_H = top / clip side)
"""
import bpy, bmesh, os
from math import radians

MM = 0.001

# ── Pod envelope (body only — lid adds LID_H below) ─────────────────
POD_L, POD_W, POD_H = 45, 24, 25
POD_R = 2.0                   # vertical edge fillet

# ── Clip channel (rail-slide on temple arm) ─────────────────────────
# Caliper your dupe's arm at the hinge. Typical Wayfarer: 5 × 4 mm.
ARM_W, ARM_H = 5.0, 4.0
CH_INTERFERENCE = 0.15        # snugness — drop to 0.10 if too tight
CH_W = ARM_W - CH_INTERFERENCE
CH_H = ARM_H - CH_INTERFERENCE
CH_FLOOR = 1.0                # solid floor above clip (thick = stronger clip)

# ── Components (L × W × H in mm) ────────────────────────────────────
XIAO = (21.0, 17.5, 4.0)      # XIAO ESP32-S3 Sense
AMP  = (19.4, 17.8, 3.0)      # MAX98357A
BATT = (30.0, 20.0, 6.0)      # 300 mAh LiPo

# ── Features ────────────────────────────────────────────────────────
CAM_D      = 4.0              # camera hole diameter, front face
USB_W, USB_H = 9.5, 3.5       # USB-C slot
SPK_WIRE_D = 2.0              # speaker wire pass-through, rear face
WALL       = 1.5              # outer wall thickness
FLOOR_ABOVE_LID = 0.6         # thin floor between lid cavity and components

# ── Lid ─────────────────────────────────────────────────────────────
LID_H   = 2.0                 # lid thickness
LID_FIT = 0.15                # friction interference on lid perimeter
LID_INSET = 0.8               # lid steps inboard this much (hides seam)

# ── Derived ─────────────────────────────────────────────────────────
# Clip channel sits at the TOP of the pod. Channel floor = POD_H - CH_H.
# Components live BELOW the channel floor, down to the lid cavity.
CLIP_FLOOR_Z = POD_H - CH_H                           # = 21.15 with defaults
COMP_TOP_Z   = CLIP_FLOOR_Z - CH_FLOOR                # top of component bay
COMP_BOT_Z   = LID_H + FLOOR_ABOVE_LID                # bottom of component bay
COMP_H       = COMP_TOP_Z - COMP_BOT_Z                # available stack height

# ── helpers ─────────────────────────────────────────────────────────

def clear():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):  bpy.data.meshes.remove(m)

def box(name, dims, center):
    dx, dy, dz = (d*MM for d in dims)
    cx, cy, cz = (c*MM for c in center)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, cz))
    o = bpy.context.active_object
    o.name, o.scale = name, (dx, dy, dz)
    bpy.ops.object.transform_apply(scale=True)
    return o

def cyl(name, r, depth, center, rot=(0,0,0)):
    cx, cy, cz = (c*MM for c in center)
    bpy.ops.mesh.primitive_cylinder_add(radius=r*MM, depth=depth*MM, vertices=48,
                                         location=(cx, cy, cz), rotation=rot)
    o = bpy.context.active_object; o.name = name
    return o

def diff(base, tool):
    m = base.modifiers.new(f"d_{tool.name}", 'BOOLEAN')
    m.operation, m.solver, m.object = 'DIFFERENCE', 'EXACT', tool
    bpy.context.view_layer.objects.active = base
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(tool, do_unlink=True)

def round_vertical_edges(obj, r):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(obj.data)
    for e in bm.edges:
        v1, v2 = e.verts
        if abs(v1.co.x - v2.co.x) < 1e-6 and abs(v1.co.y - v2.co.y) < 1e-6:
            e.select = True
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.mesh.bevel(offset=r*MM, segments=6, profile=0.5, affect='EDGES')
    bpy.ops.object.mode_set(mode='OBJECT')

def export_stl(obj, path):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True,
                              global_scale=1000.0)
    except AttributeError:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True,
                                 global_scale=1000.0)

def check_manifold(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    nm = sum(1 for e in bm.edges if not e.is_manifold); bm.free()
    return nm

def cleanup(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

# ── build body ───────────────────────────────────────────────────────

clear()

# 1. Pod outer shell — sits atop the lid, so Z starts at LID_H
body = box("body", (POD_L, POD_W, POD_H),
           (POD_L/2, 0, LID_H + POD_H/2))
round_vertical_edges(body, POD_R)

# 2. Clip channel — rail-slides onto temple arm. Full-length + 2mm overhang.
diff(body, box("channel", (POD_L + 4, CH_W, CH_H),
               (POD_L/2, 0, LID_H + CLIP_FLOOR_Z + CH_H/2)))

# 3. Component bay — one big open cavity under the clip floor.
#    Components drop in through the bottom (lid opening).
bay_dims = (POD_L - 2*WALL, POD_W - 2*WALL, COMP_H)
diff(body, box("bay", bay_dims,
               (POD_L/2, 0, LID_H + COMP_BOT_Z + COMP_H/2)))

# 4. Lid rabbet — shallow step around the bottom perimeter where lid sits.
#    Inner rectangle extends LID_H tall so the lid sits flush with the pod floor.
rabbet_dims = (POD_L - 2*LID_INSET, POD_W - 2*LID_INSET, LID_H)
diff(body, box("rabbet", rabbet_dims,
               (POD_L/2, 0, LID_H/2)))

# 5. Camera hole — front face (-X), centered on XIAO's vertical position.
cam_z = LID_H + COMP_BOT_Z + COMP_H/2
diff(body, cyl("cam", CAM_D/2, 10,
               (2, 0, cam_z), rot=(0, radians(90), 0)))

# 6. USB-C slot — on outer side face (+Y), near hinge end (reachable while worn).
usb_x = 10
diff(body, box("usb", (USB_W, 10, USB_H),
               (usb_x, POD_W/2 - 2, cam_z)))

# 7. Speaker wire pass-through — rear face (+X), low on body.
diff(body, cyl("spk_wire", SPK_WIRE_D/2, 10,
               (POD_L - 2, 0, LID_H + COMP_BOT_Z + 2),
               rot=(0, radians(90), 0)))

cleanup(body)

# ── build lid ────────────────────────────────────────────────────────

lid_dims = (POD_L - 2*LID_INSET - LID_FIT,
            POD_W - 2*LID_INSET - LID_FIT,
            LID_H)
lid = box("lid", lid_dims, (POD_L/2, 0, LID_H/2))
round_vertical_edges(lid, POD_R - LID_INSET)
cleanup(lid)

# ── finalise + export ────────────────────────────────────────────────

bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'

here = os.path.dirname(os.path.abspath(__file__))
body_out = os.path.join(here, "ar_glasses_pod_v0_body.stl")
lid_out  = os.path.join(here, "ar_glasses_pod_v0_lid.stl")
export_stl(body, body_out)
export_stl(lid,  lid_out)

body_nm = check_manifold(body)
lid_nm  = check_manifold(lid)

print(f"\n── ar_glasses_pod_v0 ─────────────────────────")
print(f"  body: {body_out}")
print(f"    tris={len(body.data.polygons)} verts={len(body.data.vertices)} "
      f"non-manifold={body_nm} {'FAIL' if body_nm else 'OK'}")
print(f"  lid:  {lid_out}")
print(f"    tris={len(lid.data.polygons)} verts={len(lid.data.vertices)} "
      f"non-manifold={lid_nm} {'FAIL' if lid_nm else 'OK'}")
print(f"  envelope: {POD_L} x {POD_W} x {POD_H + LID_H} mm")
print(f"  component bay: {POD_L - 2*WALL:.1f} x {POD_W - 2*WALL:.1f} x {COMP_H:.1f} mm")
print(f"  clip channel:  {CH_W:.2f} x {CH_H:.2f} mm  (arm {ARM_W} x {ARM_H}, interference {CH_INTERFERENCE})")
