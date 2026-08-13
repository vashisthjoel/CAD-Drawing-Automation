import os
import re
import sqlite3
from typing import Dict, Optional, Tuple

from src.editing.template_metadata import load_template_metadata


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "data", "master_templates")
DB_PATH = os.path.join(BASE_DIR, "data", "templates.db")


def _detect_canopy_from_filename(file_name: str) -> bool:
    name = str(file_name).lower()
    return "canopy" in name or "with_canopy" in name or "with canopy" in name


def init_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS jb_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL UNIQUE,
            height_mm INTEGER NOT NULL,
            width_mm INTEGER NOT NULL,
            depth_mm INTEGER NOT NULL,
            material TEXT NOT NULL,
            canopy_required INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Safe migration for old database that does not have canopy_required column.
    cursor.execute("PRAGMA table_info(jb_templates)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "canopy_required" not in existing_columns:
        cursor.execute(
            "ALTER TABLE jb_templates "
            "ADD COLUMN canopy_required INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()
    conn.close()


def extract_material(filename: str) -> str:
    name = filename.upper()
    if "SS316" in name:
        return "SS316L"
    if "SS304" in name:
        return "SS304L"
    if "MS" in name or "CRCA" in name:
        return "CRCA"
    if "AL" in name or "ALUMINIUM" in name:
        return "ALUMINIUM"
    return "CRCA"


def sync_database_with_physical_files():
    init_database()

    if not os.path.exists(TEMPLATES_DIR):
        print(f"[WARNING] Template directory missing. Creating folder at: {TEMPLATES_DIR}")
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jb_templates")

    physical_files = [
        f for f in os.listdir(TEMPLATES_DIR)
        if f.lower().endswith(".dxf")
    ]

    dim_pattern = re.compile(
        r"(?P<h>\d+)\s*[xX]\s*(?P<w>\d+)\s*[xX]\s*(?P<d>\d+)"
    )

    found_count = 0

    for file_name in physical_files:
        match = dim_pattern.search(file_name)
        if not match:
            print(f"[SKIP] Could not detect HxWxD dimensions in filename: {file_name}")
            continue

        h = int(match.group("h"))
        w = int(match.group("w"))
        d = int(match.group("d"))
        material = extract_material(file_name)
        canopy_flag = 1 if _detect_canopy_from_filename(file_name) else 0

        cursor.execute(
            """
            INSERT INTO jb_templates
            (file_name, height_mm, width_mm, depth_mm, material, canopy_required)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_name, h, w, d, material, canopy_flag),
        )

        found_count += 1

    conn.commit()
    conn.close()

    print(
        f"[DATABASE SYNC] Successfully cataloged "
        f"{found_count} physical DXF template(s) from directory."
    )


def _load_rows(target_material: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT file_name, height_mm, width_mm, depth_mm, material, canopy_required
        FROM jb_templates
        WHERE UPPER(material) = ?
        """,
        (target_material.upper(),),
    )
    rows = cursor.fetchall()

    if not rows:
        cursor.execute(
            """
            SELECT file_name, height_mm, width_mm, depth_mm, material, canopy_required
            FROM jb_templates
            """
        )
        rows = cursor.fetchall()

    conn.close()
    return rows


def find_closest_template(
    target_h: int,
    target_w: int,
    target_d: int,
    target_material: str,
    canopy_required: Optional[bool] = None,
    **kwargs,
) -> Tuple[str, float, Dict[str, object]]:
    """
    Finds closest template by size/material.

    Canopy behavior:
    - canopy_required=True  -> prefer templates with canopy.
    - canopy_required=False -> prefer templates without canopy.
    - canopy_required=None  -> normal matching, but no hard canopy filter.

    This function remains backward compatible with old calls.
    """

    sync_database_with_physical_files()

    rows = _load_rows(target_material)

    if not rows:
        raise FileNotFoundError(
            f"No available templates registered in SQLite database. "
            f"Ensure files exist in {TEMPLATES_DIR}"
        )

    normalized_rows = []

    for file_name, h, w, d, material, canopy_flag in rows:
        filename_canopy = _detect_canopy_from_filename(file_name)
        template_canopy = bool(canopy_flag) or filename_canopy

        normalized_rows.append(
            {
                "file_name": file_name,
                "height_mm": int(h),
                "width_mm": int(w),
                "depth_mm": int(d),
                "material": material,
                "canopy_required": template_canopy,
            }
        )

    candidates = normalized_rows

    # Strong canopy preference, but safe fallback if no matching group exists.
    if canopy_required is True:
        canopy_candidates = [
            row for row in normalized_rows
            if row["canopy_required"] is True
        ]

        if canopy_candidates:
            candidates = canopy_candidates
        else:
            print(
                "[MATCHER WARNING] Canopy was requested, but no canopy DXF "
                "template was found. Falling back to normal candidates."
            )

    elif canopy_required is False:
        non_canopy_candidates = [
            row for row in normalized_rows
            if row["canopy_required"] is False
        ]

        if non_canopy_candidates:
            candidates = non_canopy_candidates

    best_match = None
    best_metadata = None
    min_delta = float("inf")

    for row in candidates:
        h = row["height_mm"]
        w = row["width_mm"]
        d = row["depth_mm"]

        size_delta = (
            abs(float(target_h) - h)
            + abs(float(target_w) - w)
            + abs(float(target_d) - d)
        )

        # Small tie-breaker: prefer exact canopy match if requested.
        canopy_penalty = 0
        if canopy_required is True and row["canopy_required"] is False:
            canopy_penalty = 100000
        elif canopy_required is False and row["canopy_required"] is True:
            canopy_penalty = 10000

        total_delta = size_delta + canopy_penalty

        if total_delta < min_delta:
            min_delta = total_delta
            best_match = row["file_name"]
            best_metadata = {
                "height_mm": h,
                "width_mm": w,
                "depth_mm": d,
                "material": row["material"],
                "file_name": row["file_name"],
                "canopy_required": row["canopy_required"],
                "requested_canopy_required": canopy_required,
                "match_delta": size_delta,
            }

    if best_match is None:
        raise FileNotFoundError("No suitable template found.")

    template_path = os.path.join(TEMPLATES_DIR, best_match)

    best_metadata = load_template_metadata(template_path, best_metadata)

    # Force active canopy status into metadata after metadata loading.
    best_metadata["canopy_required"] = bool(
        best_metadata.get("canopy_required")
        or _detect_canopy_from_filename(best_match)
    )
    best_metadata["requested_canopy_required"] = canopy_required

    return best_match, min_delta, best_metadata


sync_database_with_physical_files()