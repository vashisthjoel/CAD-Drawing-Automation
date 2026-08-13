
"""Interactive Streamlit UI for the prompt-driven CAD editing workflow."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src.canopy_routing import (
    detect_canopy_required,
    ensure_canopy_note,
)
from src.editing.dxf_edit_executor import execute_edit_plan
from src.editing.dxf_validation_report import (
    build_user_report,
    validation_report_path,
)
from src.editing.edit_plan import EditPlan, generate_manual_edit_map_plan_svg
from src.llm_interpreter import LLMDrawingInterpreter
from src.matcher import find_closest_template, sync_database_with_physical_files
from src.parser import JunctionBoxNoteParser
from src.rendering.dxf_preview_renderer import render_dxf_preview


st.set_page_config(page_title="AI Interactive CAD Studio", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "data", "master_templates")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
EDIT_PLAN_SVG_PATH = os.path.join(
    OUTPUTS_DIR,
    "handle_review",
    "edit_plan.svg",
)
REFERENCE_EDIT_MAP_PATH = os.path.join(
    TEMPLATES_DIR,
    "standard jb(080MS11) 1000X800X300.edit_map.json",
)
SHOW_INTERNAL_EDIT_MAP_DEBUG = (
    os.environ.get("PYRO_DEBUG_EDIT_MAP", "").strip() == "1"
)


def _new_working_paths(matched_file: str) -> tuple[str, str]:
    stem = Path(matched_file).stem
    suffix = Path(matched_file).suffix or ".dxf"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dxf_path = os.path.join(
        OUTPUTS_DIR,
        f"LIVE_MOD_{stem}_{run_id}{suffix}",
    )
    return dxf_path, os.path.splitext(dxf_path)[0] + ".png"


def _init_session_state() -> None:
    defaults = {
        "source_template_path": None,
        "working_dxf_path": None,
        "output_dxf_path": None,
        "output_preview_path": None,
        "validation_report_path": None,
        "current_filename": None,
        "selected_template": None,
        "template_width": None,
        "template_height": None,
        "template_depth": None,
        "template_metadata": None,
        "target_width": None,
        "target_height": None,
        "target_depth": None,
        "last_report": None,
        "parsed_spec": None,
        "edit_plan_svg_path": None,
        "edit_plan_svg_error": None,
        "staging_warnings": [],
        "preview_version": 0,
        "canopy_present": True,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _refresh_edit_plan_svg(
    operation_reports: list[dict] | None = None,
) -> None:
    if not SHOW_INTERNAL_EDIT_MAP_DEBUG:
        st.session_state.edit_plan_svg_path = None
        st.session_state.edit_plan_svg_error = None
        return
    dxf_path = st.session_state.working_dxf_path
    metadata = st.session_state.template_metadata or {}
    if not dxf_path or not os.path.exists(dxf_path):
        st.session_state.edit_plan_svg_path = None
        return
    try:
        selected_template = (
            st.session_state.selected_template
            or Path(dxf_path).name
        )
        candidate_path = (
            Path(TEMPLATES_DIR)
            / "edit_maps"
            / f"{Path(selected_template).stem}.manual.template.json"
        )
        st.session_state.edit_plan_svg_path = generate_manual_edit_map_plan_svg(
            dxf_path=dxf_path,
            selected_template_file_name=selected_template,
            output_path=EDIT_PLAN_SVG_PATH,
            reference_schema_path=REFERENCE_EDIT_MAP_PATH,
            candidate_json_path=(
                str(candidate_path) if candidate_path.is_file() else None
            ),
            show_all_handles=False,
        )
        st.session_state.edit_plan_svg_error = None
    except Exception as exc:
        st.session_state.edit_plan_svg_path = None
        st.session_state.edit_plan_svg_error = str(exc)


def _stage_template(input_data: str | dict) -> None:
    sync_database_with_physical_files()
    if isinstance(input_data, str):
        from src.input_parsers.drawing_input_parser import parse_drawing_input
        parsed_data = parse_drawing_input(notes_text=input_data)
    else:
        parsed_data = input_data

    target_h = parsed_data.get("height_mm") or 500
    target_w = parsed_data.get("width_mm") or 500
    target_d = parsed_data.get("depth_mm") or 300
    material = parsed_data.get("body_material") or "CRCA"
    canopy_required = parsed_data.get("canopy_required")

    matched_file, _, template_metadata = find_closest_template(
        target_h,
        target_w,
        target_d,
        material,
        canopy_required=canopy_required,
    )

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    source_template_path = os.path.join(TEMPLATES_DIR, matched_file)
    working_dxf_path, output_preview_path = _new_working_paths(matched_file)
    output_dxf_path = working_dxf_path

    shutil.copy2(source_template_path, working_dxf_path)
    staging_warnings = []
    if "warnings" in parsed_data:
        staging_warnings.extend(parsed_data["warnings"])
    if canopy_required:
        canopy_note_result = ensure_canopy_note(working_dxf_path)
        if canopy_note_result.get("warning"):
            staging_warnings.append(canopy_note_result["warning"])
    render_dxf_preview(working_dxf_path, output_preview_path)

    st.session_state.source_template_path = source_template_path
    st.session_state.working_dxf_path = working_dxf_path
    st.session_state.output_dxf_path = output_dxf_path
    st.session_state.output_preview_path = output_preview_path
    st.session_state.validation_report_path = validation_report_path(output_dxf_path)
    st.session_state.current_filename = os.path.basename(output_dxf_path)
    st.session_state.selected_template = matched_file
    st.session_state.template_width = float(template_metadata["width_mm"])
    st.session_state.template_height = float(template_metadata["height_mm"])
    st.session_state.template_depth = float(template_metadata["depth_mm"])
    st.session_state.template_metadata = dict(template_metadata)
    st.session_state.target_width = float(target_w)
    st.session_state.target_height = float(target_h)
    st.session_state.target_depth = float(target_d)
    st.session_state.canopy_present = canopy_required
    st.session_state.last_report = None
    st.session_state.parsed_spec = dict(parsed_data)
    st.session_state.staging_warnings = staging_warnings
    st.session_state.preview_version += 1
    _refresh_edit_plan_svg()

    print(f"[GA] canopy_required={canopy_required}")
    print(f"[GA] selected_template={matched_file}")
    print(
        "[GA] selected_edit_map="
        f"{template_metadata.get('edit_map_path')}"
    )
    print(
        "[GA] edit_map_status="
        f"{template_metadata.get('edit_map_status', 'standard')}"
    )

    edit_map_state = (
        "available" if template_metadata.get("edit_map_available") else "not available"
    )
    st.success(
        f"Staged `{matched_file}` | Size: "
        f"{template_metadata['height_mm']}x{template_metadata['width_mm']}x"
        f"{template_metadata['depth_mm']} mm."
    )
    if (
        template_metadata.get("canopy_required")
        and not template_metadata.get("edit_map_available")
    ):
        st.warning(
            "Canopy drawing generated. Geometry edits are disabled until "
            "the canopy edit map is verified and complete."
        )
    elif (
        template_metadata.get("canopy_required")
        and template_metadata.get("component_edit_available")
        and not template_metadata.get("global_resize_available")
    ):
        st.info(
            "Canopy drawing generated. Component edits are available; "
            "global width, height, and depth resize is blocked until the "
            "runtime edit map is verified."
        )
    else:
        st.info(f"Drawing editability: {edit_map_state}")
    for warning in staging_warnings:
        st.warning(f"Warning: {warning}")


def _build_edit_plan(operations: list[dict]) -> EditPlan:
    metadata = dict(st.session_state.template_metadata or {})
    metadata["canopy_present"] = st.session_state.canopy_present
    return EditPlan(
        source_template_path=st.session_state.source_template_path,
        working_dxf_path=st.session_state.working_dxf_path,
        output_dxf_path=st.session_state.output_dxf_path,
        output_preview_path=st.session_state.output_preview_path,
        template_metadata=metadata,
        template_width_mm=st.session_state.template_width,
        template_height_mm=st.session_state.template_height,
        template_depth_mm=st.session_state.template_depth,
        target_width_mm=st.session_state.target_width,
        target_height_mm=st.session_state.target_height,
        target_depth_mm=st.session_state.target_depth,
        operations=operations,
    )


def _show_report(report: dict) -> None:
    applied = report.get("operations_applied", [])
    blocked = report.get("operations_blocked", [])
    failed = report.get("operations_failed", [])

    if report.get("success"):
        st.success(
            f"Successfully applied {len(applied)} operation(s). "
            f"Modified entities: {report.get('modified_entity_count', 0)}."
        )
        st.session_state.preview_version += 1
    elif not applied:
        st.info("No DXF changes were applied.")

    for operation in blocked:
        st.warning(operation.get("reason", "Operation was blocked."))
    for operation in failed:
        st.error(operation.get("reason", "Operation failed."))
    if report.get("warnings"):
        st.caption("\n".join(report["warnings"]))
    for error in report.get("errors", []):
        st.error(error)


def _show_preview() -> None:
    preview_path = st.session_state.output_preview_path
    dxf_path = st.session_state.output_dxf_path

    if not preview_path or not os.path.exists(preview_path):
        st.info("No active blueprint staged.")
        return

    st.markdown("### Preview rendered from current DXF")
    with open(preview_path, "rb") as preview_file:
        st.image(preview_file.read(), width="stretch")
    st.caption(f"Viewport Frame Version: v{st.session_state.preview_version}")

    if dxf_path and os.path.exists(dxf_path):
        with open(dxf_path, "rb") as drawing_file:
            st.download_button(
                "Export Final DXF",
                data=drawing_file.read(),
                file_name=st.session_state.current_filename,
                mime="application/dxf",
                width="stretch",
            )

    if st.session_state.last_report:
        st.markdown("### Drawing Result")
        metadata = st.session_state.template_metadata or {}
        user_report = build_user_report(
            st.session_state.last_report,
            metadata,
            st.session_state.selected_template or "",
            {
                "width_mm": st.session_state.target_width,
                "height_mm": st.session_state.target_height,
                "depth_mm": st.session_state.target_depth,
            },
        )
        st.json(user_report)

    edit_plan_svg_path = st.session_state.edit_plan_svg_path
    if (
        SHOW_INTERNAL_EDIT_MAP_DEBUG
        and edit_plan_svg_path
        and os.path.exists(edit_plan_svg_path)
    ):
        st.markdown("### Developer Edit-Map Plan")
        with open(edit_plan_svg_path, "rb") as edit_plan_file:
            edit_plan_bytes = edit_plan_file.read()
        edit_plan_svg = edit_plan_bytes.decode("utf-8")
        components.html(
            (
                "<style>"
                "html, body { margin: 0; background: white; }"
                "svg { width: 100%; height: auto; display: block; }"
                "</style>"
                f"{edit_plan_svg}"
            ),
            height=950,
            scrolling=True,
        )
        st.download_button(
            "Download Engineer Review SVG",
            data=edit_plan_bytes,
            file_name="edit_plan.svg",
            mime="image/svg+xml",
            width="stretch",
        )
    elif SHOW_INTERNAL_EDIT_MAP_DEBUG and st.session_state.edit_plan_svg_error:
        st.warning(
            "Engineer review SVG could not be generated: "
            f"{st.session_state.edit_plan_svg_error}"
        )


_init_session_state()

st.title("Interactive AI Prompt-Driven CAD Engine")
st.subheader("DXF-first drawing modification workflow")

controls, preview = st.columns([1, 1.4])

with controls:
    st.markdown("### 1. Select closest DXF template")
    input_mode = st.radio("Input Format Selection:", ["Notes", "Excel/CSV"])
    
    parsed_spec = None
    customer_input = ""
    
    if input_mode == "Notes":
        sample_notes = (
            "BOX SIZE: 1000 x 600 x 300\n"
            "MATERIAL: CRCA\n"
            "NOTES: ALL DRAWINGS ARE STANDARD UNLESS CUSTOMIZED."
        )
        customer_input = st.text_area(
            "Engineering Notes:",
            value=sample_notes,
            height=150,
        )
    else:
        uploaded_file = st.file_uploader(
            "Upload Excel or CSV spreadsheet:",
            type=["csv", "xlsx", "xls"]
        )
        if uploaded_file is not None:
            os.makedirs(OUTPUTS_DIR, exist_ok=True)
            temp_path = os.path.join(OUTPUTS_DIR, uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            try:
                from src.input_parsers.drawing_input_parser import parse_drawing_input
                parsed_spec = parse_drawing_input(spreadsheet_path=temp_path)
                st.markdown("**Extracted Values:**")
                st.markdown(f"- Width: {parsed_spec.get('width')}")
                st.markdown(f"- Height/Length: {parsed_spec.get('height')}")
                st.markdown(f"- Depth: {parsed_spec.get('depth')}")
                st.markdown(f"- Material: {parsed_spec.get('material')}")
                canopy_req_str = "Yes" if parsed_spec.get('canopy_required') is True else ("No" if parsed_spec.get('canopy_required') is False else "Not specified")
                st.markdown(f"- Canopy Required: {canopy_req_str}")
            except Exception as exc:
                st.error(f"Spreadsheet parsing failed: {exc}")
                parsed_spec = None

    if st.button("Match and Stage Drawing", type="primary", width="stretch"):
        try:
            if input_mode == "Notes":
                _stage_template(customer_input)
            else:
                if parsed_spec is None:
                    st.warning("Please upload a valid Excel/CSV spreadsheet first.")
                else:
                    _stage_template(parsed_spec)
        except Exception as exc:
            st.error(f"Template staging failed: {exc}")

    st.markdown("---")
    st.markdown("### 2. Apply requested DXF edits")

    if st.session_state.working_dxf_path:
        st.info(f"Editing working DXF: `{st.session_state.current_filename}`")
        metadata = st.session_state.template_metadata or {}
        if not metadata.get("edit_map_available"):
            if metadata.get("canopy_required"):
                st.warning(
                    "This canopy drawing is viewable, but geometry edits "
                    "require a verified canopy edit map."
                )
            else:
                st.warning(
                    "This template has no verified geometry edit map. Text "
                    "replacements are available, but width, height, and depth "
                    "changes will be blocked to prevent drawing corruption."
                )
        elif metadata.get("component_edit_available") and not metadata.get(
            "global_resize_available"
        ):
            st.info(
                "Component edits are available from the runtime component "
                "registry. Width, height, and depth resize remain blocked "
                "until map verification passes."
            )

        user_prompt = st.text_input(
            "What would you like to alter?",
            placeholder="e.g., Move LEFT-1 by +50 mm",
        )
        if st.button("Apply Edit Plan", width="stretch"):
            if not user_prompt.strip():
                st.warning("Enter a drawing edit request first.")
            else:
                with st.spinner("Building edit plan and modifying DXF..."):
                    try:
                        operations = LLMDrawingInterpreter().interpret_prompt(
                            user_prompt
                        )
                        if not operations:
                            st.warning("No edit operations were recognized.")
                        else:
                            report = execute_edit_plan(_build_edit_plan(operations))
                            st.session_state.last_report = report
                            
                            for op in report.get("operations_applied", []):
                                if op.get("operation") == "remove_canopy":
                                    st.session_state.canopy_present = False
                                    
                            st.session_state.output_dxf_path = report.get(
                                "output_dxf_path",
                                st.session_state.output_dxf_path,
                            )
                            st.session_state.output_preview_path = report.get(
                                "output_preview_path",
                                st.session_state.output_preview_path,
                            )
                            _refresh_edit_plan_svg(
                                report.get("operations_applied", [])
                            )
                            _show_report(report)
                    except Exception as exc:
                        st.error(f"Operation failed: {exc}")
    else:
        st.info("Stage a drawing template first.")

with preview:
    _show_preview()
