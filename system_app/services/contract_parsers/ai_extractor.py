"""OpenAI API で契約書テキストから契約条件を構造化抽出する"""
import logging

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_TIMEOUT = 30

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "contract_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "worker_name":               {"type": ["string", "null"]},
                "project_name":              {"type": ["string", "null"]},
                "upstream_company_name":     {"type": ["string", "null"]},
                "valid_from":                {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "valid_to":                  {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "unit_price":                {"type": ["integer", "null"]},
                "is_fixed_fee":              {"type": ["boolean", "null"]},
                "travel_expense_included":   {"type": ["boolean", "null"]},
                "lower_limit_hour":          {"type": ["number", "null"]},
                "upper_limit_hours":         {"type": ["number", "null"]},
                "settlement_unit_minutes":   {"type": ["integer", "null"]},
                "excess_unit_price":         {"type": ["integer", "null"]},
                "deduction_unit_price":      {"type": ["integer", "null"]},
                "upstream_payment_terms":    {"type": ["integer", "null"], "description": "支払サイト（日数）"},
                "bank_holiday_handling":     {"type": ["string", "null"]},
                "upstream_timesheet_collection_method": {"type": ["string", "null"]},
                "highlighted_coords":        {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "抽出根拠となったセル座標のリスト（Excelの場合）"
                },
                "confidence":                {"type": "number", "description": "0.0〜1.0"},
                "notes":                     {"type": "string", "description": "不明点や注意事項"},
            },
            "required": [
                "worker_name", "project_name", "upstream_company_name",
                "valid_from", "valid_to", "unit_price", "is_fixed_fee",
                "travel_expense_included", "lower_limit_hour", "upper_limit_hours",
                "settlement_unit_minutes", "excess_unit_price", "deduction_unit_price",
                "upstream_payment_terms", "bank_holiday_handling",
                "upstream_timesheet_collection_method",
                "highlighted_coords", "confidence", "notes",
            ],
            "additionalProperties": False,
        },
    },
}


def extract_contract_fields(text, file_type="xlsx"):
    """
    契約書テキストから契約条件を抽出する。

    Parameters
    ----------
    text : str
        Excelの場合は "座標: 値" 形式のテキスト。PDFの場合は生テキスト。
    file_type : str
        "xlsx" or "pdf"

    Returns
    -------
    dict  抽出結果
    """
    from openai import OpenAI
    client = OpenAI(timeout=_TIMEOUT)

    coord_note = ""
    if file_type == "xlsx":
        coord_note = (
            "入力はExcelのセル情報（座標: 値）の形式です。\n"
            "抽出根拠となったセル座標を highlighted_coords に列挙してください。\n"
        )

    prompt = (
        "以下は業務委託契約書（個別契約書）の内容です。\n"
        f"{coord_note}"
        "契約条件の各フィールドを抽出してJSONで返してください。\n\n"
        "【注意事項】\n"
        "- unit_price は税別の月額単価（円）\n"
        "- upstream_payment_terms は支払サイトの日数（例: 翌月末=30, 翌々月10日=40）\n"
        "- settlement_unit_minutes は精算単位（分）\n"
        "- 不明な項目はnullにしてください\n"
        "- valid_from / valid_to は YYYY-MM-DD 形式\n\n"
        "【契約書内容】\n"
        f"{text}"
    )

    try:
        import json
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=_SCHEMA,
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.exception("AI contract extraction failed")
        return {
            "error": str(e),
            "worker_name": None,
            "project_name": None,
            "upstream_company_name": None,
            "valid_from": None,
            "valid_to": None,
            "unit_price": None,
            "is_fixed_fee": None,
            "travel_expense_included": None,
            "lower_limit_hour": None,
            "upper_limit_hours": None,
            "settlement_unit_minutes": None,
            "excess_unit_price": None,
            "deduction_unit_price": None,
            "upstream_payment_terms": None,
            "bank_holiday_handling": None,
            "upstream_timesheet_collection_method": None,
            "highlighted_coords": [],
            "confidence": 0.0,
            "notes": f"エラー: {e}",
        }
