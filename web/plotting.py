"""Dependency-light SVG plan preview for the Streamlit presentation layer."""

from __future__ import annotations

from html import escape

from .layout_editor import ModulePlacement, identified_interfaces
from .i18n import t


HORIZONTAL_COLOR = "#B9D8EA"
VERTICAL_COLOR = "#F4C99B"


def render_layout_svg(
    rows: int,
    columns: int,
    placements: list[ModulePlacement],
    show_interfaces: bool = True,
    occupied_cells: set[tuple[int, int]] | None = None,
) -> str:
    cell = 58
    margin = 26
    legend = 48
    width = max(2 * margin + columns * cell, 320)
    grid_left = (width - columns * cell) / 2
    height = 2 * margin + rows * cell + legend
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{escape(t("svg.preview"))}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
    ]
    for row in range(rows):
        for column in range(columns):
            x = grid_left + column * cell
            y = margin + row * cell
            occupied = occupied_cells is None or (row, column) in occupied_cells
            fill = "#F3F4F6" if occupied else "#FFFFFF"
            dash = "" if occupied else ' stroke-dasharray="4 3"'
            parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#B8BEC5" stroke-width="1"{dash}/>')
            if not occupied:
                parts.append(f'<text x="{x + cell / 2}" y="{y + cell / 2 + 4}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#A0A7AE">{escape(t("svg.void"))}</text>')
            parts.append(f'<text x="{x + 4}" y="{y + 12}" font-family="Arial, sans-serif" font-size="8" fill="#7A838B">{row},{column}</text>')
    for item in placements:
        x = grid_left + item.column * cell + 2
        y = margin + item.row * cell + 2
        module_width = (2 * cell if item.orientation == "H" else cell) - 4
        module_height = (cell if item.orientation == "H" else 2 * cell) - 4
        color = HORIZONTAL_COLOR if item.orientation == "H" else VERTICAL_COLOR
        parts.append(f'<rect x="{x}" y="{y}" width="{module_width}" height="{module_height}" rx="3" fill="{color}" stroke="#263238" stroke-width="2"/>')
        parts.append(
            f'<text x="{x + module_width / 2}" y="{y + module_height / 2 + 4}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="12" fill="#1F2933">{escape(item.orientation)}{item.module_id}</text>'
        )
    if show_interfaces:
        for start, end in identified_interfaces(placements):
            x1, y1 = grid_left + start[0] * cell, margin + start[1] * cell
            x2, y2 = grid_left + end[0] * cell, margin + end[1] * cell
            parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#6B46C1" stroke-width="4" stroke-linecap="round"/>')
    baseline = margin + rows * cell + 28
    parts.extend(
        [
            f'<rect x="{margin}" y="{baseline - 11}" width="18" height="12" fill="{HORIZONTAL_COLOR}" stroke="#263238"/>',
            f'<text x="{margin + 25}" y="{baseline}" font-family="Arial, sans-serif" font-size="11">{escape(t("svg.horizontal"))}</text>',
            f'<rect x="{margin + 132}" y="{baseline - 11}" width="18" height="12" fill="{VERTICAL_COLOR}" stroke="#263238"/>',
            f'<text x="{margin + 157}" y="{baseline}" font-family="Arial, sans-serif" font-size="11">{escape(t("svg.vertical"))}</text>',
            "</svg>",
        ]
    )
    return "".join(parts)


def render_screening_layout_svg(layout, show_interfaces: bool = True) -> str:
    from .batch_screening import placements_from_layout

    return render_layout_svg(
        layout.footprint.rows,
        layout.footprint.columns,
        placements_from_layout(layout),
        show_interfaces=show_interfaces,
        occupied_cells=set(layout.footprint.cells),
    )


__all__ = ["render_layout_svg", "render_screening_layout_svg"]
