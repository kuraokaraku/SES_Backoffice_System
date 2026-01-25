import imaplib
import email
from email.header import decode_header
import os
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from ..models import PurchaseOrder
from datetime import datetime

def search_and_save_to_vps(client_name, start_date=None):
    try:
        # 1. レンタルサーバーのメールに接続 (IMAP)
        mail = imaplib.IMAP4_SSL(settings.XSERVER_IMAP_SERVER)
        mail.login(settings.XSERVER_MAIL_USER, settings.XSERVER_MAIL_PASSWORD)
        mail.select("INBOX")

        search_query = f'SUBJECT "{client_name}"'
        if start_date:
            d_start = datetime.strptime(start_date, '%Y-%m-%d')
            search_query += f' SINCE {d_start.strftime("%d-%b-%Y")}'

        typ, data = mail.search('UTF-8', search_query)
        if typ != 'OK': return "メール検索に失敗しました。"

        count = 0
        for num in data[0].split():
            _, msg_data = mail.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])
            received_at = email.utils.parsedate_to_datetime(msg.get("Date"))

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart': continue
                filename = part.get_filename()

                if filename:
                    # ファイル名のデコード
                    decoded_name = ""
                    for s, charset in decode_header(filename):
                        if isinstance(s, bytes):
                            decoded_name += s.decode(charset or 'utf-8')
                        else:
                            decoded_name += s
                    
                    if decoded_name.lower().endswith('.pdf'):
                        # 2. VPS内のmediaフォルダに保存
                        pdf_content = part.get_payload(decode=True)
                        save_path = f"purchase_orders/{decoded_name}"

                        # 同名ファイルがあれば上書きせず保存
                        actual_path = default_storage.save(save_path, ContentFile(pdf_content))

                        # 3. DBに記録
                        PurchaseOrder.objects.create(
                            client_name=client_name,
                            received_at=received_at,
                            file=actual_path
                        )
                        count += 1

        mail.logout()
        return f"{count}件の注文書をVPSに保存しました。"

    except Exception as e:
        return f"エラー: {str(e)}"