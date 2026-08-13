import os
import shutil

import ezdxf

from src.editing.autocad_dxf_export import save_autocad_compatible_dxf
from src.editing.dxf_stretch_engine import stretch_view
from src.editing.dxf_view_indexer import build_view_index


class JunctionBoxCADEngine:
    """
    Legacy engine kept for import compatibility. New production flow should use
    EditPlan plus execute_edit_plan.
    """

    def __init__(self, templates_dir: str, output_dir: str):
        self.templates_dir = templates_dir
        self.output_dir = output_dir

    def stretch_layout(self, template_name: str, output_name: str, delta_h: float, delta_w: float, **_kwargs) -> str:
        input_path = os.path.join(self.templates_dir, template_name)
        output_path = os.path.join(self.output_dir, output_name)
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Master template drawing not found at: {input_path}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(input_path, output_path)

        doc = ezdxf.readfile(output_path)
        view_index = build_view_index(doc)
        front_view = view_index.get("FRONT VIEW")
        if front_view and delta_w:
            stretch_view(doc, front_view, axis="x", delta=delta_w, anchor="left")
        if front_view and delta_h:
            stretch_view(doc, front_view, axis="y", delta=delta_h, anchor="bottom")
        save_autocad_compatible_dxf(doc, output_path)
        return output_path
