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


def _find_billing_ym(text, filename):
    """テキストとファイル名から対象年月を探す。"""
    candidates = []

    # テキストから探す（日本語パターン優先）
    for m in _RE_YM_JA.finditer(text):
        ym = f"{m.group(1)}{int(m.group(2)):02d}"
        candidates.append({"value": ym, "confidence": 0.90, "source": "text_ja"})

    for m in _RE_YM_SLASH.finditer(text):
        ym = f"{m.group(1)}{int(m.group(2)):02d}"
        candidates.append({"value": ym, "confidence": 0.80, "source": "text_slash"})

    # ファイル名から探す
    for m in _RE_YM_COMPACT.finditer(filename):
        ym = f"{m.group(1)}{m.group(2)}"
        candidates.append({"value": ym, "confidence": 0.70, "source": "filename"})

    for m in _RE_YM_JA.finditer(filename):
        ym = f"{m.group(1)}{int(m.group(2)):02d}"
        candidates.append({"value": ym, "confidence": 0.85, "source": "filename_ja"})

    # テキスト中に「X月」だけある場合（年がない）→ ファイル名から年を補完
    month_only = re.findall(r"(?<!\d)(1[0-2]|0?[1-9])\s*月(?!\s*分)", text)
    if month_only and not candidates:
        # ファイル名から年だけ取れれば補完
        year_match = re.search(r"(20\d{2})", filename)
        if year_match:
            month = int(month_only[0])
            ym = f"{year_match.group(1)}{month:02d}"
            candidates.append({"value": ym, "confidence": 0.60, "source": "text_month_only"})

    if not candidates:
        return None

    # 最高confidence
    best = max(candidates, key=lambda c: c["confidence"])
    return best


def _find_actual_hours_from_tables(tables):
    """テーブルから合計時間を探す。"""
    candidates = []

    for table in tables:
        for ri, row in enumerate(table):
            row_text = " ".join(str(c or "") for c in row)

            # 「月間累計」「稼動日数」行の最後のセルに累計時間がある
            for kw in _TOTAL_KEYWORDS:
                if kw in row_text:
                    # 行の右端からHH:MM or 数値を探す
                    for ci in range(len(row) - 1, -1, -1):
                        cell = str(row[ci] or "").strip()
                        if not cell:
                            continue
                        hours = _hhmm_to_hours(cell)
                        if hours and hours > 50:  # 月間の合計っぽい値
                            candidates.append({
                                "value": hours,
                                "confidence": 0.85,
                                "source": f"table_keyword({kw})",
                            })
                            break
                    break

    # テーブルから開始/終了時刻を計算するフォールバック
    if not candidates:
        total = _calc_hours_from_start_end(tables)
        if total:
            candidates.append({
                "value": total,
                "confidence": 0.70,
                "source": "calc_start_end",
            })

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["confidence"])
    return best


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


def _find_actual_hours_from_text(text):
    """テキストから合計時間を探す（テーブル取得に失敗した場合のフォールバック）。"""
    lines = text.split("\n")
    for line in lines:
        for kw in _TOTAL_KEYWORDS:
            if kw in line:
                hours = _hhmm_to_hours(line)
                if hours and hours > 50:
                    return {
                        "value": hours,
                        "confidence": 0.75,
                        "source": f"text_keyword({kw})",
                    }
                # 数値を探す
                nums = _RE_HOURS_NUM.findall(line)
                for n in nums:
                    v = Decimal(n)
                    if 50 < v < 300:
                        return {
                            "value": v,
                            "confidence": 0.65,
                            "source": f"text_num({kw})",
                        }
    return None


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
    all_text = ""
    all_tables = []

    for page in pdf.pages:
        text = page.extract_text() or ""
        all_text += text + "\n"
        all_tables.extend(page.extract_tables())

    pdf.close()

    # --- billing_ym ---
    billing_ym = _find_billing_ym(all_text, filename)

    # --- actual_hours ---
    actual_hours = _find_actual_hours_from_tables(all_tables)
    if not actual_hours:
        actual_hours = _find_actual_hours_from_text(all_text)

    # --- travel_amount（PDFでは基本取れない、None固定） ---
    travel_amount = None

    return {
        "billing_ym": billing_ym,
        "actual_hours": actual_hours,
        "travel_amount": travel_amount,
    }
