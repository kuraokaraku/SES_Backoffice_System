"""Excel 契約書パーサ: セル値抽出 + HTML変換 + ハイライト"""
import re
import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string


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

    # データのある実際の列範囲を検出
    actual_max_col = 1
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.column > actual_max_col:
                actual_max_col = cell.column

    # ハイライト座標の列も含める
    for coord in highlight_coords:
        col_letter = re.match(r"([A-Z]+)", coord)
        if col_letter:
            col_idx = column_index_from_string(col_letter.group(1))
            if col_idx > actual_max_col:
                actual_max_col = col_idx

    max_col = actual_max_col

    # Excelの列幅を取得（ポイント→px変換: 1pt ≈ 8px）
    col_widths = {}
    for col_letter, col_dim in ws.column_dimensions.items():
        col_idx = column_index_from_string(col_letter)
        if col_idx <= max_col:
            w = col_dim.width or 8
            col_widths[col_idx] = max(30, min(int(w * 7), 200))  # 30〜200px

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

    # 列ヘッダー行
    header_tds = ['<th style="background:#e9ecef; border:1px solid #ccc; padding:2px 4px; font-size:10px; text-align:center; min-width:20px;">#</th>']
    for col_idx in range(1, max_col + 1):
        w = col_widths.get(col_idx, 60)
        header_tds.append(
            f'<th style="background:#e9ecef; border:1px solid #ccc; padding:2px 4px; '
            f'font-size:10px; text-align:center; width:{w}px;">'
            f'{get_column_letter(col_idx)}</th>'
        )
    html_rows = [f"<tr>{''.join(header_tds)}</tr>"]

    for row_idx in range(1, ws.max_row + 1):
        # 空行はスキップ（ただしハイライト行は表示）
        row_has_data = any(
            ws.cell(row=row_idx, column=c).value is not None
            for c in range(1, max_col + 1)
        )
        row_has_highlight = any(
            f"{get_column_letter(c)}{row_idx}" in highlight_coords
            for c in range(1, max_col + 1)
        )
        if not row_has_data and not row_has_highlight:
            continue

        row_bg = "#fafafa" if row_idx % 2 == 0 else "#ffffff"
        tds = [
            f'<td style="background:#e9ecef; border:1px solid #ccc; padding:2px 4px; '
            f'font-size:10px; text-align:center; color:#666;">{row_idx}</td>'
        ]

        for col_idx in range(1, max_col + 1):
            coord = f"{get_column_letter(col_idx)}{row_idx}"
            merge_info = merged.get((row_idx, col_idx))

            if merge_info and not merge_info.get("is_origin"):
                continue

            cell = ws.cell(row=row_idx, column=col_idx)
            val = cell.value if cell.value is not None else ""
            val_str = str(val).strip() if val != "" else ""

            attrs = ""
            if merge_info and merge_info.get("is_origin"):
                rs = merge_info["rowspan"]
                cs = merge_info["colspan"]
                if rs > 1:
                    attrs += f' rowspan="{rs}"'
                if cs > 1:
                    attrs += f' colspan="{cs}"'

            if coord in highlight_coords:
                bg = "#ffe066"
                border = "2px solid #f0a500"
                fw = "bold"
                title = f' title="{coord}"'
            else:
                bg = row_bg
                border = "1px solid #dee2e6"
                fw = "normal"
                title = ""

            style = (
                f"background:{bg}; border:{border}; padding:3px 6px; "
                f"font-size:11px; white-space:pre-wrap; vertical-align:top; "
                f"font-weight:{fw}; max-width:200px; overflow:hidden; text-overflow:ellipsis;"
            )
            tds.append(f'<td{attrs} style="{style}" data-coord="{coord}"{title}>{val_str}</td>')

        html_rows.append(f"<tr>{''.join(tds)}</tr>")

    table = (
        '<div style="overflow:auto;">'
        '<table style="border-collapse:collapse; font-size:11px; table-layout:fixed;">'
        + "".join(html_rows)
        + "</table></div>"
    )
    return table
