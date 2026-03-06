# ITFLシステム

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
- **契約書AI自動入力**: Excel/PDFをアップロードするとOpenAI APIがフィールドを抽出して自動入力

### 入金・支払管理（`/ar/`, `/ap/`）
- 請求書への入金消込
- 下位への買掛・支払管理

## 業務フロー

```
契約書アップロード → AI自動入力 → 契約登録
        ↓
勤務表アップロード → 自動パース → 請求書生成 → 編集・確認 → Excelダウンロード → 送付済チェック → 入金消込
```

## 技術スタック

- Python 3.11 / Django 4.2
- Bootstrap 5.3（CDN）
- SQLite（開発） / MySQL（本番）
- openpyxl（Excel入出力）
- pdfplumber（PDF解析）
- OpenAI API gpt-4o-mini（契約書AI抽出）

## セットアップ

```bash
# 1. クローン
git clone git@github.com:kuraokaraku/SES_Backoffice_System.git
cd itfl_app

# 2. 仮想環境の作成と起動
python -m venv .venv
source .venv/bin/activate

# 3. ライブラリのインストール
pip install -r requirements.txt

# 4. 環境変数の設定
cp .env.example .env  # なければ手動で作成
# .env に以下を記載:
# SECRET_KEY=your-secret-key
# DEBUG=True
# OPENAI_API_KEY=your-openai-key

# 5. DBのマイグレーション
python manage.py migrate

# 6. 管理ユーザー作成（初回のみ）
python manage.py createsuperuser

# 7. サーバー起動
python manage.py runserver
```

ブラウザで http://127.0.0.1:8000/ にアクセス。

停止は `Ctrl + C`。

## テスト

```bash
DEBUG=True python manage.py test --verbosity=2
```

- テスト用の一時DBを自動作成・実行後に削除（本番DBに影響なし）
- 63本のテストで請求計算・契約判定・ページ疎通を検証

## CI/CD

`main` ブランチへのプッシュ・PRで自動実行（GitHub Actions）:

1. **テスト** — 全63本がグリーンであること
2. **デプロイ** — テスト通過後、AWS EC2 へ自動デプロイ

## プロジェクト構成

```
office_system/          Django設定（settings, urls）
system_app/
  models.py             モデル定義
  views.py              ビュー
  forms.py              フォーム
  urls.py               URLルーティング
  services/
    contracts.py              契約取得
    invoice_calculator.py     請求計算ロジック
    invoicing.py              請求書生成サービス
    invoice_exporters/        Excel出力
    timesheet_parsers/        勤務表パーサ（xlsx/pdf）
    contract_parsers/         契約書パーサ（xlsx/pdf + AI抽出）
  tests/                ユニットテスト・ビューテスト
  templates/            HTMLテンプレート
  static/img/           ロゴ等の静的ファイル
```

## 環境変数

`.env` ファイルで設定（コミット不可）:

- `SECRET_KEY` — Djangoシークレットキー
- `DEBUG` — `True` で開発モード（SQLite使用）
- `OPENAI_API_KEY` — 契約書AI抽出に使用
- `DB_NAME`, `DB_USER`, `DB_PASSWORD` — 本番MySQL接続情報
