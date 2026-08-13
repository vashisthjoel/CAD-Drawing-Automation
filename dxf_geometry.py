from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from ezdxf import bbox


BBox = Dict[str, float]


def entity_label(entity: Any) -> Dict[str, Any]:
    return {
        "type": entity.dxftype(),
        "handle": getattr(entity.dxf, "handle", None),
        "layer": getattr(entity.dxf, "layer", None),
    }


def entity_text(entity: Any) -> str:
    if entity.dxftype() == "MTEXT" and hasattr(entity, "plain_text"):
        try:
            return entity.plain_text()
        except TypeError:
            pass
    return str(getattr(entity.dxf, "text", ""))


def entity_bbox(entity: Any) -> Optional[BBox]:
    try:
        extents = bbox.extents([entity])
        has_data = extents.has_data() if callable(extents.has_data) else extents.has_data
        if not has_data:
            return None
        return {
            "min_x": float(extents.extmin.x),
            "max_x": float(extents.extmax.x),
            "min_y": float(extents.extmin.y),
            "max_y": float(extents.extmax.y),
        }
    except Exception:
        points = entity_points(entity)
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}


def union_bbox(boxes: Iterable[BBox]) -> Optional[BBox]:
    boxes = list(boxes)
    if not boxes:
        return None
    return {
        "min_x": min(box["min_x"] for box in boxes),
        "max_x": max(box["max_x"] for box in boxes),
        "min_y": min(box["min_y"] for box in boxes),
        "max_y": max(box["max_y"] for box in boxes),
    }


def bbox_center(box: BBox) -> Tuple[float, float]:
    return (box["min_x"] + box["max_x"]) / 2, (box["min_y"] + box["max_y"]) / 2


def point_in_bbox(x: float, y: float, box: BBox) -> bool:
    return box["min_x"] <= x <= box["max_x"] and box["min_y"] <= y <= box["max_y"]


def entity_points(entity: Any) -> list[Tuple[float, float]]:
    entity_type = entity.dxftype()
    if entity_type == "LINE":
        return [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    if entity_type == "LWPOLYLINE":
        return [(point[0], point[1]) for point in entity.get_points()]
    if entity_type in {"CIRCLE", "ARC"}:
        return [(entity.dxf.center.x, entity.dxf.center.y)]
    if entity_type in {"TEXT", "MTEXT", "INSERT"}:
        return [(entity.dxf.insert.x, entity.dxf.insert.y)]
    if entity_type == "DIMENSION":
        points = []
        for attr in ("defpoint", "defpoint2", "defpoint3", "text_midpoint"):
            if hasattr(entity.dxf, attr):
                point = getattr(entity.dxf, attr)
                points.append((point.x, point.y))
        return points
    return []


def move_entity(entity: Any, dx: float, dy: float) -> int:
    if not dx and not dy:
        return 0
    entity_type = entity.dxftype()
    moved = 0
    if entity_type == "LINE":
        for attr in ("start", "end"):
            point = getattr(entity.dxf, attr)
            setattr(entity.dxf, attr, (point.x + dx, point.y + dy, getattr(point, "z", 0.0)))
            moved += 1
    elif entity_type == "LWPOLYLINE":
        entity.set_points([(p[0] + dx, p[1] + dy) + tuple(p[2:]) for p in entity.get_points()])
        moved += 1
    elif entity_type in {"CIRCLE", "ARC"}:
        point = entity.dxf.center
        entity.dxf.center = (point.x + dx, point.y + dy, getattr(point, "z", 0.0))
        moved += 1
    elif entity_type in {"TEXT", "MTEXT", "INSERT"}:
        point = entity.dxf.insert
        entity.dxf.insert = (point.x + dx, point.y + dy, getattr(point, "z", 0.0))
        moved += 1
    elif entity_type == "DIMENSION":
        for attr in ("defpoint", "defpoint2", "defpoint3", "text_midpoint"):
            if hasattr(entity.dxf, attr):
                point = getattr(entity.dxf, attr)
                setattr(entity.dxf, attr, (point.x + dx, point.y + dy, getattr(point, "z", 0.0)))
                moved += 1
    elif entity_type == "LEADER" and hasattr(entity, "vertices"):
        entity.vertices = [(point[0] + dx, point[1] + dy, point[2] if len(point) > 2 else 0.0) for point in entity.vertices]
        moved += 1
    return moved
