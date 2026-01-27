import imaplib
import email
from email.header import decode_header
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from ..models import PurchaseOrder
from datetime import datetime, timedelta

def search_and_save_to_vps(client_name, start_date=None, end_date=None):
    try:
        if client_name:
            # 1. 全角スペースを半角スペースに置換
            # 2. 前後の余分な空白を削除
            client_name = client_name.replace('　', ' ').strip()

        print(f"DEBUG: 正規化後の検索名: '{client_name}'")

        # 1. 検索範囲（開始・終了）の確定
        now = datetime.now()

        # 終了時刻の設定（空なら現在時刻）
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            # その日の23:59:59まで含める
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = now

        # 開始時刻の設定（空なら終了時刻の1ヶ月前）
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            start_dt = start_dt.replace(hour=0, minute=0, second=0)
        else:
            start_dt = end_dt - timedelta(days=30)

        print(f"DEBUG: 検索範囲 {start_dt} ～ {end_dt}")

        # IMAP接続
        mail = imaplib.IMAP4_SSL(settings.XSERVER_IMAP_SERVER)
        mail.login(settings.XSERVER_MAIL_USER, settings.XSERVER_MAIL_PASSWORD)
        mail.select("INBOX")

        # IMAPのSINCE/BEFORE（日付単位）で広めに検索
        # ※BEFOREは指定日の「翌日」を指定するとその日中が含ませる
        since_str = start_dt.strftime("%d-%b-%Y")
        before_str = (end_dt + timedelta(days=1)).strftime("%d-%b-%Y")
        search_query = f'(SINCE {since_str} BEFORE {before_str})'

        typ, data = mail.search('UTF-8', search_query)
        if typ != 'OK':
            mail.logout()
            return "メールの取得に失敗しました。"

        # メールIDのリストを取得
        mail_ids = data[0].split()

        # 新しいメールから順に処理（逆順にする）
        for num in reversed(mail_ids):
            _, msg_data = mail.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])

            # 本文の抽出
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    # text/plain（テキスト形式）かつ 添付ファイルでないものを抽出
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        if payload:
                            # メールのヘッダーから文字コードを取得（なければutf-8と仮定）
                            charset = part.get_content_charset() or 'utf-8'
                            try:
                                # ignoreではなくreplaceを使うと、化けた箇所が「?」になりエラーで止まらない
                                body += payload.decode(charset, errors="replace")
                            except Exception as e:
                                print(f"DEBUG: Decode Error ({charset}): {e}")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors="replace")

            # 本文中にクライアント名が含まれているかチェック
            if client_name in body:
                received_at = email.utils.parsedate_to_datetime(msg.get("Date"))

                # 添付ファイルの処理
                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart': continue
                    filename = part.get_filename()

                    if filename:
                        print (f"----- filename exist: {filename}")
                        # ファイル名のデコード
                        decoded_name = ""
                        for s, charset in decode_header(filename):
                            if isinstance(s, bytes):
                                decoded_name += s.decode(charset or 'utf-8')
                            else:
                                decoded_name += s

                        # PDFを見つけたら保存して即終了
                        if decoded_name.lower().endswith('.pdf'):
                            pdf_content = part.get_payload(decode=True)
                            # 保存パス: media/purchase_orders/YYYYMMDD_filename.pdf (重複回避のため日付付与推奨)
                            save_name = f"{received_at.strftime('%Y%m%d')}_{decoded_name}"
                            save_path = f"purchase_orders/{save_name}"

                            actual_path = default_storage.save(save_path, ContentFile(pdf_content))

                            # DB登録
                            PurchaseOrder.objects.create(
                                client_name=client_name,
                                received_at=received_at,
                                file=actual_path
                            )
                            print (f"-------  upload finished")
                            mail.logout()
                            return f"最新のメール（{received_at.strftime('%Y/%m/%d')}受信）から注文書「{decoded_name}」を取得し、VPSに保存しました。"

        mail.logout()
        print (f"----- finished")
        return f"指定された条件で「{client_name}」を含む注文書メールは見つかりませんでした。"

    except Exception as e:
        return f"エラーが発生しました: {str(e)}"