"""PDF 契約書パーサ: テキスト抽出"""
import pdfplumber


def extract_text(file_path):
    """
    PDFからテキストを抽出する。
    画像PDFの場合は空文字列を返す。

    Returns
    -------
    str  抽出されたテキスト全文
    """
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def is_text_pdf(file_path):
    """テキスト抽出可能なPDFかどうかを判定する。"""
    text = extract_text(file_path)
    return len(text.strip()) > 50
