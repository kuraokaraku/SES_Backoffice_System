# 都システム（Miya-Co）

SES事業の契約・勤務表・請求を一元管理するWebアプリケーション。

## 主な機能

### 勤務表回収（`/timesheets/`）
- 月別ダッシュボードで回収状況を一覧管理
- Excel/PDFアップロード → 実稼働時間を自動パース
- 未回収・受領済・処理済のステータス管理
- 期限超過の強調表示

### 請求書管理（`/invoices/`）
- 勤務表から請求書を自動生成（契約条件ベースで計算）
- Excel雛型テンプレートへのエクスポート
- 明細の手動編集、契約条件からの再計算
- 月別表示、送付済チェック管理

### 契約管理（`/party/`）
- ワーカー・上位会社・下位会社・営業担当の登録
- 契約条件（単価・精算幅・超過/控除単価・支払サイト等）
- 案件ごとのアサインメント管理

## 業務フロー

```
契約登録 → 勤務表アップロード → 自動パース → 請求書生成 → 編集・確認 → Excelダウンロード → 送付済チェック
```

## 技術スタック

- Python / Django 4.2
- Bootstrap 5.3（CDN）
- SQLite（開発）
- openpyxl（Excel入出力）

## セットアップ

```bash
# 1. クローン
git clone git@github.com:itfl0801/itfl_app.git
cd itfl_app

# 2. 仮想環境の作成と起動
python -m venv .venv
source .venv/bin/activate

# 3. ライブラリのインストール
pip install -r requirements.txt

# 4. DBのマイグレーション
python manage.py migrate

# 5. 管理ユーザー作成（初回のみ）
python manage.py createsuperuser

# 6. サーバー起動
python manage.py runserver
```

ブラウザで http://127.0.0.1:8000/ にアクセス。

停止は `Ctrl + C`。

## プロジェクト構成

```
office_system/          Django設定（settings, urls）
system_app/
  models.py             モデル定義
  views.py              ビュー
  forms.py              フォーム
  urls.py               URLルーティング
  services/
    contracts.py         契約取得
    invoice_calculator.py 請求計算ロジック
    invoicing.py         請求書生成サービス
    invoice_exporters/   Excel出力
    timesheet_parsers/   勤務表パーサ（xlsx/pdf）
  templates/             HTMLテンプレート
  static/img/            ロゴ等の静的ファイル
```

## 環境変数

`.env` ファイルで設定（コミット不可）:

- `SECRET_KEY` — Djangoシークレットキー
- `DEBUG` — `True` で開発モード
