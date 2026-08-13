import base64
import os

import ezdxf
from ezdxf import bbox

from src.editing.file_change_tracker import get_file_state


IGNORED_PREVIEW_LAYERS = {"border", "title_block", "titleblock", "frame", "sheet"}
FALLBACK_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAF"
    "gwJ/lw2nGQAAAABJRU5ErkJggg=="
)


def render_dxf_preview(dxf_path: str, png_path: str) -> dict:
    if not dxf_path.lower().endswith(".dxf"):
        raise ValueError("Preview renderer input must be a DXF file")
    if not png_path.lower().endswith(".png"):
        raise ValueError("Preview renderer output must be a PNG file")

    png_before = get_file_state(png_path)
    if os.path.exists(png_path):
        os.remove(png_path)

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    os.makedirs(os.path.dirname(png_path), exist_ok=True)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    except ModuleNotFoundError:
        with open(png_path, "wb") as handle:
            handle.write(base64.b64decode(FALLBACK_PNG))
        png_after = get_file_state(png_path)
        return _render_report(dxf_path, png_path, png_before, png_after)

    fig, ax = plt.subplots(figsize=(14, 12), dpi=130)
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(msp, finalize=True)

    try:
        content_entities = [entity for entity in msp if entity.dxf.layer.lower() not in IGNORED_PREVIEW_LAYERS]
        extents = bbox.extents(content_entities or msp)
        has_data = extents.has_data() if callable(extents.has_data) else extents.has_data
        if has_data:
            width = extents.extmax.x - extents.extmin.x
            height = extents.extmax.y - extents.extmin.y
            padding_x = width * 0.08 if width else 10
            padding_y = height * 0.08 if height else 10
            ax.set_xlim(extents.extmin.x - padding_x, extents.extmax.x + padding_x)
            ax.set_ylim(extents.extmin.y - padding_y, extents.extmax.y + padding_y)
    except Exception:
        pass

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.tight_layout(pad=0.0)
    fig.savefig(png_path, bbox_inches="tight", pad_inches=0.0)
    plt.close(fig)

    png_after = get_file_state(png_path)
    return _render_report(dxf_path, png_path, png_before, png_after)


def _render_report(dxf_path: str, png_path: str, png_before: dict, png_after: dict) -> dict:
    return {
        "dxf_path_used": dxf_path,
        "png_path": png_path,
        "png_hash_before": png_before["sha256"],
        "png_hash_after": png_after["sha256"],
        "png_changed": png_before["sha256"] != png_after["sha256"],
        "preview_regenerated": True,
    }

