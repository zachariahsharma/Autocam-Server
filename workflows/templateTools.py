import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional


_TEMPLATE_NS = "http://www.hsmworks.com/namespace/hsmworks/document/template"
_NUM_RE = re.compile(r"[-+]?(?:\d+\.\d+|\d+|\.\d+)(?:[eE][-+]?\d+)?")


def _q(tag: str) -> str:
    return f"{{{_TEMPLATE_NS}}}{tag}"


def _as_bool_str(value: Any) -> str:
    return "true" if bool(value) else "false"


def _as_int01_str(value: Any) -> str:
    return "1" if bool(value) else "0"


def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _as_int01_str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Match the precision typically seen in Fusion template files.
        return f"{value:.8g}"
    return str(value)


def _parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUM_RE.search(value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _normalize_desc(value: str) -> str:
    value = (value or "").strip().lower()
    # Normalize whitespace and quote variants.
    value = value.replace("“", '"').replace("”", '"').replace("’", "'")
    value = re.sub(r"\s+", " ", value)
    return value


def _material_aliases(material_name: str) -> list[str]:
    name = (material_name or "").strip().lower()
    aliases: list[str] = []
    if not name:
        return aliases

    if any(token in name for token in ("al", "alu", "alum", "6061", "aluminum", "aluminium")):
        aliases.extend(["aluminium", "aluminum", "alum", "alu", "6061"])
    if "poly" in name or "pc" == name:
        aliases.extend(["polycarb", "polycarbonate", "poly", "pc"])
    if "mdf" in name:
        aliases.append("mdf")
    if "acrylic" in name:
        aliases.extend(["acrylic", "pmma"])

    # Also try the raw material name.
    aliases.append(name)
    # Deduplicate while preserving order.
    seen = set()
    out: list[str] = []
    for a in aliases:
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def _choose_preset(tool: dict, material_name: Optional[str]) -> Optional[dict]:
    presets = (
        tool.get("start-values", {})
        .get("presets", [])
    )
    if not isinstance(presets, list) or not presets:
        return None

    aliases = _material_aliases(material_name or "")
    if aliases:
        for preset in presets:
            preset_name = str(preset.get("name") or "").lower()
            if any(alias in preset_name for alias in aliases):
                return preset

    for preset in presets:
        preset_name = str(preset.get("name") or "").strip().lower()
        if preset_name == "default preset":
            return preset

    return presets[0]


def load_tool_library_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Tool library JSON must be an object, got {type(data)}")
    return data


def _index_tools(tool_library: dict) -> dict:
    tools = tool_library.get("data")
    if not isinstance(tools, list):
        tools = []

    by_desc: dict[str, dict] = {}
    by_type: dict[str, list[dict]] = {}
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        desc = _normalize_desc(str(tool.get("description") or ""))
        if desc and desc not in by_desc:
            by_desc[desc] = tool
        tool_type = str(tool.get("type") or "")
        by_type.setdefault(tool_type, []).append(tool)

    return {
        "version": tool_library.get("version"),
        "tools": tools,
        "by_desc": by_desc,
        "by_type": by_type,
    }


def _required_tool_signature(tool_elem: ET.Element) -> dict:
    desc = (tool_elem.findtext(_q("description")) or "").strip()
    tool_type = str(tool_elem.get("type") or "").strip()

    diameter = None
    for expr in tool_elem.findall(f"{_q('expressions')}/{_q('expression')}"):
        if expr.get("parameterKey") == "tool_diameter":
            diameter = _parse_number(expr.get("value"))
            break

    return {
        "description": desc,
        "type": tool_type,
        "diameter": diameter,
    }


def _find_matching_tool(signature: dict, indexes: list[dict]) -> Optional[tuple[dict, dict]]:
    desc = _normalize_desc(signature.get("description") or "")
    tool_type = signature.get("type") or ""
    diameter = signature.get("diameter")

    if desc:
        for idx in indexes:
            tool = idx["by_desc"].get(desc)
            if tool:
                return tool, idx

    if diameter is None:
        return None

    for idx in indexes:
        candidates = idx["by_type"].get(tool_type, [])
        for tool in candidates:
            tool_dia = _parse_number(tool.get("geometry", {}).get("DC"))
            if tool_dia is None:
                tool_dia = _parse_number(tool.get("expressions", {}).get("tool_diameter"))
            if tool_dia is None:
                continue
            if abs(tool_dia - float(diameter)) <= 1e-4:
                return tool, idx

    return None


def _strip_outer_quotes(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and ((value[0] == value[-1] == "'") or (value[0] == value[-1] == '"')):
        return value[1:-1]
    return value


def _ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    child = parent.find(_q(tag))
    if child is None:
        child = ET.SubElement(parent, _q(tag))
    return child


def _reset_children(elem: ET.Element) -> None:
    for child in list(elem):
        elem.remove(child)


def _apply_tool_to_elem(
    template_elem: ET.Element,
    tool_elem: ET.Element,
    tool: dict,
    tool_library_version: Optional[Any],
    material_name: Optional[str],
) -> None:
    preset = _choose_preset(tool, material_name)

    tool_guid = tool.get("guid")
    if tool_guid:
        tool_elem.set("guid", str(tool_guid))

    tool_unit = str(tool.get("unit") or tool_elem.get("unit") or "inches")
    tool_elem.set("unit", tool_unit)

    tool_type = str(tool.get("type") or tool_elem.get("type") or "")
    if tool_type:
        tool_elem.set("type", tool_type)

    if tool_library_version is not None:
        tool_elem.set("tool-library-version", str(tool_library_version))

    tool_desc = str(tool.get("description") or "")
    desc_node = _ensure_child(tool_elem, "description")
    desc_node.text = tool_desc

    expressions_node = _ensure_child(tool_elem, "expressions")
    _reset_children(expressions_node)
    expressions = tool.get("expressions", {})
    if isinstance(expressions, dict):
        for key, value in expressions.items():
            expr = ET.SubElement(expressions_node, _q("expression"))
            expr.set("parameterKey", str(key))
            expr.set("value", str(value))

    post = tool.get("post-process", {})
    if not isinstance(post, dict):
        post = {}
    nc_node = _ensure_child(tool_elem, "nc")
    nc_node.set("break-control", _as_int01_str(post.get("break-control")))
    nc_node.set("diameter-offset", str(post.get("diameter-offset", 1)))
    nc_node.set("length-offset", str(post.get("length-offset", 1)))
    nc_node.set("live-tool", _as_int01_str(post.get("live")))
    nc_node.set("manual-tool-change", _as_int01_str(post.get("manual-tool-change")))
    nc_node.set("number", str(post.get("number", 1)))
    nc_node.set("turret", str(post.get("turret", 0)))

    coolant_mode = None
    if preset:
        coolant_mode = preset.get("tool-coolant")
    coolant_mode = str(coolant_mode or "disabled")
    coolant_node = _ensure_child(tool_elem, "coolant")
    coolant_node.set("mode", coolant_mode)

    material_expr = ""
    if isinstance(expressions, dict):
        material_expr = str(expressions.get("tool_material") or "")
    material_node = _ensure_child(tool_elem, "material")
    material_node.set("name", _strip_outer_quotes(material_expr) or "unspecified")

    geometry = tool.get("geometry", {})
    if not isinstance(geometry, dict):
        geometry = {}
    body_node = _ensure_child(tool_elem, "body")
    body_map = {
        "assembly-gauge-length": geometry.get("assemblyGaugeLength"),
        "body-length": geometry.get("LB"),
        "diameter": geometry.get("DC"),
        "flute-length": geometry.get("LCF"),
        "number-of-flutes": geometry.get("NOF"),
        "overall-length": geometry.get("OAL"),
        "shaft-diameter": geometry.get("SFDM"),
        "shoulder-length": geometry.get("shoulder-length"),
        "shoulder-diameter": geometry.get("shoulder-diameter"),
        "taper-angle": geometry.get("SIG"),
        "thread-pitch": geometry.get("TP"),
        "thread-profile-angle": geometry.get("thread-profile-angle"),
    }
    for attr, val in body_map.items():
        if val is None:
            continue
        body_node.set(attr, _fmt_num(val))

    # Best-effort motion + presets (Fusion will still load even if some values differ).
    motion_node = _ensure_child(tool_elem, "motion")
    if preset:
        n = _parse_number(preset.get("n")) or _parse_number(preset.get("n_ramp")) or 0
        n_ramp = _parse_number(preset.get("n_ramp")) or n
        v_f = _parse_number(preset.get("v_f")) or 0
        v_f_lead_in = _parse_number(preset.get("v_f_leadIn")) or v_f
        v_f_lead_out = _parse_number(preset.get("v_f_leadOut")) or v_f
        v_f_plunge = _parse_number(preset.get("v_f_plunge")) or 0
        v_f_ramp = _parse_number(preset.get("v_f_ramp")) or 0
        v_f_retract = _parse_number(preset.get("v_f_retract")) or 0
        v_f_transition = _parse_number(preset.get("v_f_transition")) or v_f

        ramp_angle_deg = _parse_number(preset.get("ramp-angle"))
        ramp_angle_internal = None
        if ramp_angle_deg is not None:
            # Fusion template files appear to store ramp angle in 5° units (10° -> 2).
            ramp_angle_internal = float(ramp_angle_deg) / 5.0

        motion_updates = {
            "cutting-feedrate": v_f,
            "entry-feedrate": v_f_lead_in,
            "exit-feedrate": v_f_lead_out,
            "plunge-feedrate": v_f_plunge,
            "ramp-feedrate": v_f_ramp,
            "retract-feedrate": v_f_retract,
            "transition-feedrate": v_f_transition,
            "spindle-rpm": n,
            "ramp-spindle-rpm": n_ramp,
        }
        for key, val in motion_updates.items():
            motion_node.set(key, _fmt_num(val))
        if ramp_angle_internal is not None:
            motion_node.set("ramp-angle", _fmt_num(ramp_angle_internal))

    presets_node = _ensure_child(tool_elem, "presets")
    _reset_children(presets_node)
    if preset and preset.get("guid"):
        preset_id = str(preset.get("guid"))
        template_elem.set("toolPresetId", f"{{{preset_id}}}")

        preset_node = ET.SubElement(presets_node, _q("preset"))
        preset_node.set("description", str(preset.get("description") or ""))
        preset_node.set("id", f"{{{preset_id}}}")
        preset_node.set("name", str(preset.get("name") or "Default preset"))

        preset_exprs = preset.get("expressions", {})
        if not isinstance(preset_exprs, dict):
            preset_exprs = {}

        def add_param(key: str, value: Any, expression: Optional[str] = None) -> None:
            param = ET.SubElement(preset_node, _q("parameter"))
            param.set("key", key)
            param.set("value", str(value))
            if expression is not None:
                param.set("expression", str(expression))

        tool_unit_is_inches = tool_unit.lower().startswith("inch")

        def mm_value(inches_value: float) -> float:
            return inches_value * 25.4 if tool_unit_is_inches else inches_value

        add_param("tool_useFeedPerRevolution", _as_bool_str(preset.get("use-feed-per-revolution", False)))

        coolant_expr = preset_exprs.get("tool_coolant") or f"'{coolant_mode}'"
        add_param("tool_coolant", coolant_mode, expression=coolant_expr)

        n = _parse_number(preset.get("n")) or 0
        n_expr = preset_exprs.get("tool_spindleSpeed") or (f"{_fmt_num(n)} rpm" if n else None)
        add_param("tool_spindleSpeed", _fmt_num(n), expression=n_expr)

        n_ramp = _parse_number(preset.get("n_ramp"))
        if n_ramp is not None:
            add_param("tool_rampSpindleSpeed", _fmt_num(n_ramp))

        v_f = _parse_number(preset.get("v_f"))
        if v_f is not None:
            v_f_expr = preset_exprs.get("tool_feedCutting")
            add_param("tool_feedCutting", _fmt_num(mm_value(v_f)), expression=v_f_expr)
            add_param("tool_feedEntry", _fmt_num(mm_value(_parse_number(preset.get("v_f_leadIn")) or v_f)))
            add_param("tool_feedExit", _fmt_num(mm_value(_parse_number(preset.get("v_f_leadOut")) or v_f)))
            add_param("tool_feedTransition", _fmt_num(mm_value(_parse_number(preset.get("v_f_transition")) or v_f)))

        v_f_plunge = _parse_number(preset.get("v_f_plunge"))
        if v_f_plunge is not None:
            v_f_plunge_expr = preset_exprs.get("tool_feedPlunge")
            add_param("tool_feedPlunge", _fmt_num(mm_value(v_f_plunge)), expression=v_f_plunge_expr)

        v_f_ramp = _parse_number(preset.get("v_f_ramp"))
        if v_f_ramp is not None:
            v_f_ramp_expr = preset_exprs.get("tool_feedRamp")
            add_param("tool_feedRamp", _fmt_num(mm_value(v_f_ramp)), expression=v_f_ramp_expr)

        v_f_retract = _parse_number(preset.get("v_f_retract"))
        if v_f_retract is not None:
            add_param("tool_feedRetract", _fmt_num(mm_value(v_f_retract)))

        material_info = preset.get("material", {})
        if isinstance(material_info, dict):
            add_param("tool_presetMaterialCategory", str(material_info.get("category") or "all"))
            add_param("tool_presetMaterialQuery", str(material_info.get("query") or ""))

        stepdown = _parse_number(preset.get("stepdown"))
        if stepdown is not None:
            stepdown_expr = preset_exprs.get("tool_stepdown")
            add_param("tool_stepdown", _fmt_num(mm_value(stepdown)), expression=stepdown_expr)

        stepover = _parse_number(preset.get("stepover"))
        if stepover is not None:
            stepover_expr = preset_exprs.get("tool_stepover")
            add_param("tool_stepover", _fmt_num(mm_value(stepover)), expression=stepover_expr)

        ramp_angle_deg = _parse_number(preset.get("ramp-angle"))
        if ramp_angle_deg is not None:
            ramp_angle_expr = preset_exprs.get("tool_rampAngle")
            add_param("tool_rampAngle", _fmt_num(float(ramp_angle_deg) / 5.0), expression=ramp_angle_expr)


def patch_cam_template_with_tool_libraries(
    template_path: str,
    output_path: str,
    tool_library_paths: list[str],
    *,
    material_name: Optional[str] = None,
) -> dict:
    if not tool_library_paths:
        raise ValueError("tool_library_paths must not be empty")

    indexes: list[dict] = []
    for path in tool_library_paths:
        lib = load_tool_library_json(path)
        indexes.append(_index_tools(lib))

    ET.register_namespace("", _TEMPLATE_NS)
    tree = ET.parse(template_path)
    root = tree.getroot()

    replaced = 0
    missing: list[dict] = []

    for template_elem in root.findall(f".//{_q('template')}"):
        tool_elem = template_elem.find(_q("tool"))
        if tool_elem is None:
            continue

        signature = _required_tool_signature(tool_elem)
        match = _find_matching_tool(signature, indexes)
        if not match:
            missing.append(signature)
            continue

        tool, idx = match
        _apply_tool_to_elem(
            template_elem,
            tool_elem,
            tool,
            tool_library_version=idx.get("version"),
            material_name=material_name,
        )
        replaced += 1

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return {
        "replaced": replaced,
        "missing": missing,
        "output_path": output_path,
    }
