"""汎用 PDF 勤務表パーサ（pdfplumber + キーワードマッチング）"""
import re
from decimal import Decimal

import pdfplumber


# 年月パターン
_RE_YM_JA = re.compile(r"(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月")
_RE_YM_SLASH = re.compile(r"(20\d{2})[/\-\.](0?[1-9]|1[0-2])(?![0-9])")
_RE_YM_COMPACT = re.compile(r"(20\d{2})(0[1-9]|1[0-2])")

# 時間パターン (HH:MM or 数値)
_RE_HHMM = re.compile(r"(\d{1,3}):(\d{2})")
_RE_HOURS_NUM = re.compile(r"(\d{1,3}(?:\.\d+)?)")

# 合計キーワード
_TOTAL_KEYWORDS = ["月間累計", "合計時間", "実働合計", "稼働合計", "勤務合計",
                   "作業時間合計", "就業時間合計", "稼働時間合計", "勤務時間合計",
                   "実作業時間合計", "累計", "合計"]


def _hhmm_to_hours(text):
    """'146:00' -> Decimal('146.00'), '8:30' -> Decimal('8.5')"""
    m = _RE_HHMM.search(str(text))
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        return Decimal(str(h)) + Decimal(str(mm)) / Decimal("60")
    return None


def _find_billing_ym(pages, filename):
    """ページごとのテキスト検索で対象年月を探す（bbox付き）。"""
    candidates = []

    for page_idx, page in enumerate(pages):
        # page.search() でテキスト位置を取得
        for m in _RE_YM_JA.finditer(page.extract_text() or ""):
            ym = f"{m.group(1)}{int(m.group(2)):02d}"
            # search() で bbox を取得
            bbox = _search_text_bbox(page, m.group(0))
            candidates.append({
                "value": ym, "confidence": 0.90, "source": "text_ja",
                "page_number": page_idx, "bbox": bbox,
            })

        for m in _RE_YM_SLASH.finditer(page.extract_text() or ""):
            ym = f"{m.group(1)}{int(m.group(2)):02d}"
            bbox = _search_text_bbox(page, m.group(0))
            candidates.append({
                "value": ym, "confidence": 0.80, "source": "text_slash",
                "page_number": page_idx, "bbox": bbox,
            })

    # ファイル名から探す（bbox なし）
    for m in _RE_YM_COMPACT.finditer(filename):
        ym = f"{m.group(1)}{m.group(2)}"
        candidates.append({"value": ym, "confidence": 0.70, "source": "filename"})

    for m in _RE_YM_JA.finditer(filename):
        ym = f"{m.group(1)}{int(m.group(2)):02d}"
        candidates.append({"value": ym, "confidence": 0.85, "source": "filename_ja"})

    # テキスト中に「X月」だけある場合（年がない）→ ファイル名から年を補完
    all_text = "\n".join((p.extract_text() or "") for p in pages)
    month_only = re.findall(r"(?<!\d)(1[0-2]|0?[1-9])\s*月(?!\s*分)", all_text)
    if month_only and not candidates:
        year_match = re.search(r"(20\d{2})", filename)
        if year_match:
            month = int(month_only[0])
            ym = f"{year_match.group(1)}{month:02d}"
            candidates.append({"value": ym, "confidence": 0.60, "source": "text_month_only"})

    if not candidates:
        return None, []

    best = max(candidates, key=lambda c: c["confidence"])
    sorted_cands = sorted(candidates, key=lambda c: c["confidence"], reverse=True)
    return best, sorted_cands[:5]


def _extract_bbox_context(page, bbox, left_expand=200, right_expand=50, v_expand=15):
    """bbox 近傍の words を拾ってコンテキスト文字列を返す。最大150文字。"""
    if not bbox:
        return ""
    try:
        x0 = max(0, bbox[0] - left_expand)
        top = max(0, bbox[1] - v_expand)
        x1 = bbox[2] + right_expand
        bottom = bbox[3] + v_expand
        words = page.extract_words()
        nearby = [
            w["text"] for w in words
            if w["x0"] >= x0 and w["top"] >= top
            and w["x1"] <= x1 and w["bottom"] <= bottom
        ]
        return " ".join(nearby)[:150]
    except Exception:
        return ""


def _search_text_bbox(page, text):
    """page.search() で テキストの bbox を取得。見つからなければ None。"""
    try:
        results = page.search(text)
        if results:
            r = results[0]
            return [r["x0"], r["top"], r["x1"], r["bottom"]]
    except Exception:
        pass
    return None


def _find_actual_hours_from_tables(pages):
    """find_tables() を使って合計時間をbbox付きで探す。"""
    candidates = []

    for page_idx, page in enumerate(pages):
        tables = page.find_tables()
        for table_obj in tables:
            text_rows = table_obj.extract()
            row_objs = table_obj.rows  # CellGroup objects with .cells
            if not text_rows:
                continue

            for ri, row in enumerate(text_rows):
                row_text = " ".join(str(c or "") for c in row)

                for kw in _TOTAL_KEYWORDS:
                    if kw in row_text:
                        # 行の右端から HH:MM or 数値を探す
                        for ci in range(len(row) - 1, -1, -1):
                            cell = str(row[ci] or "").strip()
                            if not cell:
                                continue
                            hours = _hhmm_to_hours(cell)
                            if hours and hours > 50:
                                # セルの bbox を取得
                                cell_bbox = _get_cell_bbox_from_row(row_objs, ri, ci)
                                candidates.append({
                                    "value": hours,
                                    "confidence": 0.85,
                                    "source": f"table_keyword({kw})",
                                    "page_number": page_idx,
                                    "bbox": cell_bbox,
                                    "context": _extract_bbox_context(page, cell_bbox) if cell_bbox else row_text[:150],
                                })
                                break
                        break

    # テーブルから開始/終了時刻を計算するフォールバック
    if not candidates:
        all_tables = []
        for page in pages:
            all_tables.extend(page.extract_tables())
        total = _calc_hours_from_start_end(all_tables)
        if total:
            candidates.append({
                "value": total,
                "confidence": 0.70,
                "source": "calc_start_end",
            })

    if not candidates:
        return None, []

    best = max(candidates, key=lambda c: c["confidence"])
    sorted_cands = sorted(candidates, key=lambda c: c["confidence"], reverse=True)
    return best, sorted_cands[:5]


def _get_cell_bbox_from_row(row_objs, row_idx, col_idx):
    """Table.rows (CellGroup list) から (row_idx, col_idx) のセルの bbox を取得。"""
    if not row_objs or row_idx >= len(row_objs):
        return None
    row_obj = row_objs[row_idx]
    if not hasattr(row_obj, 'cells') or col_idx >= len(row_obj.cells):
        return None
    c = row_obj.cells[col_idx]
    if c is None:
        return None
    return [c[0], c[1], c[2], c[3]]


def _calc_hours_from_start_end(tables):
    """開始/終了時刻のペアから合計時間を計算する。"""
    total_minutes = 0
    found_any = False

    for table in tables:
        for ri, row in enumerate(table):
            label = " ".join(str(c or "") for c in row[:3])
            if "開始" in label and "時刻" in label:
                # 2行下に終了時刻がある想定
                end_ri = None
                for offset in [1, 2, 3]:
                    if ri + offset < len(table):
                        end_label = " ".join(str(c or "") for c in table[ri + offset][:3])
                        if "終了" in end_label and "時刻" in end_label:
                            end_ri = ri + offset
                            break
                if end_ri is None:
                    continue

                start_row = row
                end_row = table[end_ri]
                for ci in range(3, min(len(start_row), len(end_row))):
                    s = str(start_row[ci] or "").strip()
                    e = str(end_row[ci] or "").strip()
                    if s and e and ":" in s and ":" in e:
                        try:
                            sh, sm = map(int, s.split(":"))
                            eh, em = map(int, e.split(":"))
                            worked = (eh * 60 + em) - (sh * 60 + sm) - 60  # 昼休憩1h
                            if 0 < worked < 720:  # 0〜12h
                                total_minutes += worked
                                found_any = True
                        except (ValueError, TypeError):
                            pass

    if found_any and total_minutes > 0:
        return Decimal(str(round(total_minutes / 60, 2)))
    return None


def _find_actual_hours_from_text(pages):
    """ページごとのテキストから合計時間をbbox付きで探す。"""
    candidates = []
    for page_idx, page in enumerate(pages):
        text = page.extract_text() or ""
        lines = text.split("\n")
        for line in lines:
            for kw in _TOTAL_KEYWORDS:
                if kw in line:
                    hours = _hhmm_to_hours(line)
                    if hours and hours > 50:
                        bbox = _search_text_bbox(page, kw)
                        candidates.append({
                            "value": hours,
                            "confidence": 0.75,
                            "source": f"text_keyword({kw})",
                            "page_number": page_idx,
                            "bbox": bbox,
                            "context": _extract_bbox_context(page, bbox) if bbox else line.strip()[:150],
                        })
                        break
                    # 数値を探す
                    nums = _RE_HOURS_NUM.findall(line)
                    for n in nums:
                        v = Decimal(n)
                        if 50 < v < 300:
                            bbox = _search_text_bbox(page, kw)
                            candidates.append({
                                "value": v,
                                "confidence": 0.65,
                                "source": f"text_num({kw})",
                                "page_number": page_idx,
                                "bbox": bbox,
                                "context": _extract_bbox_context(page, bbox) if bbox else line.strip()[:150],
                            })
                            break
                    break

    if not candidates:
        return None, []

    best = max(candidates, key=lambda c: c["confidence"])
    sorted_cands = sorted(candidates, key=lambda c: c["confidence"], reverse=True)
    return best, sorted_cands[:5]


def parse_timesheet_pdf_generic(path):
    """
    PDF勤務表をパースして billing_ym, actual_hours, travel_amount を返す。

    Returns
    -------
    dict  Excelパーサと同じ形式:
        {
            "billing_ym": {"value": "YYYYMM", "confidence": float, ...} | None,
            "actual_hours": {"value": Decimal, "confidence": float, ...} | None,
            "travel_amount": {"value": Decimal, "confidence": float, ...} | None,
        }
    """
    from pathlib import Path
    filename = Path(path).name

    pdf = pdfplumber.open(path)
    pages = pdf.pages

    # --- billing_ym ---
    billing_ym, bym_candidates = _find_billing_ym(pages, filename)

    # --- actual_hours ---
    actual_hours, hours_candidates = _find_actual_hours_from_tables(pages)
    if not actual_hours:
        actual_hours, text_hours_candidates = _find_actual_hours_from_text(pages)
        # テーブル候補とテキスト候補をマージ
        hours_candidates = hours_candidates + text_hours_candidates
        hours_candidates = sorted(hours_candidates, key=lambda c: c["confidence"], reverse=True)[:5]

    # --- travel_amount（PDFでは基本取れない、None固定） ---
    travel_amount = None

    pdf.close()

    return {
        "billing_ym": billing_ym,
        "actual_hours": actual_hours,
        "travel_amount": travel_amount,
        "candidates": {
            "billing_ym": bym_candidates,
            "actual_hours": hours_candidates,
            "travel_amount": [],
        },
    }
