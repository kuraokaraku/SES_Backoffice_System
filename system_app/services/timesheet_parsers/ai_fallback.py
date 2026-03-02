"""AI フォールバック（審判方式）: ルールベースパーサの候補から最適値を選択"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_TIMEOUT = 10  # seconds

_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "judge_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "choice": {"type": "integer"},
                "ai_confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["choice", "ai_confidence", "reason"],
            "additionalProperties": False,
        },
    },
}


def judge_actual_hours(candidates):
    """
    候補リストから最適な actual_hours を AI に選ばせる。

    Parameters
    ----------
    candidates : list[dict]
        上位5件の候補。各要素に "value", "confidence", "source"/"evidence" を含む。

    Returns
    -------
    dict  {"choice": int, "ai_confidence": float, "reason": str}
    """
    from openai import OpenAI

    client = OpenAI(timeout=_TIMEOUT)

    numbered = []
    for i, c in enumerate(candidates, 1):
        line = f"{i}. 値={c['value']}h  (スコア={c.get('confidence', '?')}, 根拠={c.get('evidence', c.get('source', '?'))})"
        ctx = c.get("context", "")
        if ctx:
            line += f"\n   周辺: {ctx}"
        numbered.append(line)
    candidate_text = "\n".join(numbered)

    response = client.responses.create(
        model=_MODEL,
        input=[{
            "role": "user",
            "content": (
                "以下は勤務表パーサが抽出した「月間実稼働時間」の候補です。\n\n"
                f"{candidate_text}\n\n"
                "月間の実稼働時間として最も妥当な値を1つ選んでください。\n"
                "通常 100〜200h 程度です。\n"
                "choice には候補番号（1始まり）、ai_confidence には確信度（0〜1）、"
                "reason には短い理由を返してください。"
            ),
        }],
        text=_RESPONSE_SCHEMA,
    )

    result_text = response.output_text
    return json.loads(result_text)


def enhance_parsed_result_with_ai(parsed):
    """
    パース結果にAI審判を適用し、actual_hours を改善する。

    ゲート条件:
    - actual_hours が None または confidence < 0.85
    - OPENAI_API_KEY が設定済み
    - 候補が1件以上

    Parameters
    ----------
    parsed : dict
        パーサの戻り値。"actual_hours", "candidates" キーを含む。

    Returns
    -------
    dict  parsed を（必要に応じて上書きして）返す。
    """
    # OPENAI_API_KEY チェック
    if not os.getenv("OPENAI_API_KEY"):
        return parsed

    # actual_hours の状態チェック
    ah = parsed.get("actual_hours")
    if ah and ah.get("value") is not None and ah.get("confidence", 0) >= 0.85:
        return parsed

    # 候補取得
    candidates = (parsed.get("candidates") or {}).get("actual_hours", [])
    if not candidates:
        return parsed

    # parse_meta 初期化
    if "parse_meta" not in parsed:
        parsed["parse_meta"] = {}

    try:
        result = judge_actual_hours(candidates)

        choice = result.get("choice")
        ai_confidence = result.get("ai_confidence", 0)
        reason = result.get("reason", "")

        # 採用条件: choice が有効範囲 かつ ai_confidence >= 0.6
        if (
            isinstance(choice, int)
            and 1 <= choice <= len(candidates)
            and ai_confidence >= 0.6
        ):
            chosen = candidates[choice - 1]
            parsed["actual_hours"] = chosen
            parsed["parse_meta"]["ai"] = {
                "used": True,
                "model": _MODEL,
                "choice": choice,
                "ai_confidence": ai_confidence,
                "reason": reason,
            }
            logger.info("AI fallback adopted: choice=%d, value=%s, confidence=%.2f",
                        choice, chosen["value"], ai_confidence)
        else:
            parsed["parse_meta"]["ai"] = {
                "used": False,
                "model": _MODEL,
                "choice": choice,
                "ai_confidence": ai_confidence,
                "reason": f"not_adopted: {reason}",
            }
            logger.info("AI fallback not adopted: choice=%s, ai_confidence=%.2f",
                        choice, ai_confidence)

    except Exception as e:
        error_type = type(e).__name__
        parsed["parse_meta"]["ai"] = {
            "used": False,
            "error": error_type,
        }
        logger.warning("AI fallback error: %s: %s", error_type, e)

    return parsed
