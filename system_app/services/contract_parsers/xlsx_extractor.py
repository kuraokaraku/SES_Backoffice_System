"""Excel 契約書パーサ: セル値抽出 + HTML変換 + ハイライト"""
import re
import openpyxl
from openpyxl.utils import get_column_letter


def extract_cells(file_path):
    """
    Excelから全セル値を取得する。

    Returns
    -------
    list[dict]  {"coord": "A1", "row": 1, "col": 1, "value": "..."}
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    cells = []
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                cells.append({
                    "coord": cell.coordinate,
                    "row": cell.row,
                    "col": cell.column,
                    "value": str(cell.value).strip(),
                })
    return cells


def cells_to_text(cells):
    """セルリストを LLM 用のテキストに変換する。"""
    lines = [f"{c['coord']}: {c['value']}" for c in cells]
    return "\n".join(lines)


def render_html(file_path, highlight_coords=None):
    """
    Excelをシンプルな HTML テーブルに変換する。
    highlight_coords: ハイライトするセル座標のリスト (例: ["D17", "G19"])
    """
    highlight_coords = set(highlight_coords or [])
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    max_row = ws.max_row
    max_col = ws.max_column

    # マージセル情報を収集
    merged = {}
    for merge in ws.merged_cells.ranges:
        min_row, min_col, max_row_m, max_col_m = (
            merge.min_row, merge.min_col, merge.max_row, merge.max_col
        )
        for r in range(min_row, max_row_m + 1):
            for c in range(min_col, max_col_m + 1):
                if r == min_row and c == min_col:
                    merged[(r, c)] = {
                        "rowspan": max_row_m - min_row + 1,
                        "colspan": max_col_m - min_col + 1,
                        "is_origin": True,
                    }
                else:
                    merged[(r, c)] = {"is_origin": False}

    html_rows = []
    for row_idx in range(1, ws.max_row + 1):
        tds = []
        for col_idx in range(1, max_col + 1):
            coord = f"{get_column_letter(col_idx)}{row_idx}"
            merge_info = merged.get((row_idx, col_idx))

            if merge_info and not merge_info.get("is_origin"):
                continue  # マージされたセルはスキップ

            cell = ws.cell(row=row_idx, column=col_idx)
            val = cell.value if cell.value is not None else ""
            val_str = str(val).strip() if val != "" else "&nbsp;"

            attrs = ""
            if merge_info and merge_info.get("is_origin"):
                rs = merge_info["rowspan"]
                cs = merge_info["colspan"]
                if rs > 1:
                    attrs += f' rowspan="{rs}"'
                if cs > 1:
                    attrs += f' colspan="{cs}"'

            style = "border:1px solid #ddd; padding:3px 6px; font-size:11px; white-space:pre-wrap; vertical-align:top;"
            if coord in highlight_coords:
                style += " background:#fff3cd; font-weight:bold;"

            tds.append(f'<td{attrs} style="{style}" data-coord="{coord}">{val_str}</td>')

        if tds:
            html_rows.append(f"<tr>{''.join(tds)}</tr>")

    table = (
        '<div style="overflow:auto; max-height:80vh;">'
        '<table style="border-collapse:collapse; font-size:11px; min-width:100%;">'
        + "".join(html_rows)
        + "</table></div>"
    )
    return table
