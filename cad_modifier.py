import ezdxf

from src.editing.autocad_dxf_export import save_autocad_compatible_dxf
from src.editing.dxf_stretch_engine import stretch_view
from src.editing.dxf_text_editor import replace_text


class ScalableCADEngine:
    """
    Legacy compatibility facade. The Streamlit app now uses EditPlan and
    execute_edit_plan so the DXF remains the only editable source of truth.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.working_doc = ezdxf.readfile(file_path)
        self.msp = self.working_doc.modelspace()

    def resize_drawing_width(self, old_val: float, new_val: float):
        delta = new_val - old_val
        points = [point for entity in self.msp for point in self._entity_points(entity)]
        if not points:
            return {"moved_entities": 0, "moved_points": 0, "skipped_entities": []}
        view_bbox = {
            "min_x": min(point.x for point in points),
            "max_x": max(point.x for point in points),
            "min_y": min(point.y for point in points),
            "max_y": max(point.y for point in points),
        }
        return stretch_view(self.working_doc, view_bbox, axis="x", delta=delta, anchor="left")

    def add_circle_cutout(self, cx: float, cy: float, radius: float, layer: str = "CUTOUT"):
        self.msp.add_circle(center=(cx, cy), radius=radius, dxfattribs={"layer": layer, "color": 1})

    def remove_circle_cutout(self, cx: float, cy: float, radius: float, tolerance: float = 10.0) -> bool:
        removed = False
        for entity in list(self.msp.query("CIRCLE")):
            if (
                abs(entity.dxf.center.x - cx) <= tolerance
                and abs(entity.dxf.center.y - cy) <= tolerance
                and abs(entity.dxf.radius - radius) <= tolerance
            ):
                self.msp.delete_entity(entity)
                removed = True
        return removed

    def update_drawing_text(self, target_text: str, new_text: str) -> bool:
        report = replace_text(self.working_doc, target_text, new_text)
        return report["replacement_count"] > 0

    def save_changes(self):
        save_autocad_compatible_dxf(self.working_doc, self.file_path)

    def _entity_points(self, entity):
        if entity.dxftype() == "LINE":
            return [entity.dxf.start, entity.dxf.end]
        if entity.dxftype() in {"CIRCLE", "ARC"}:
            return [entity.dxf.center]
        if entity.dxftype() in {"TEXT", "MTEXT", "INSERT"}:
            return [entity.dxf.insert]
        return []
