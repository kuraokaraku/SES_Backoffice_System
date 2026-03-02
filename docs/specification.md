# ITFLシステム 仕様書

**バージョン**: 1.0
**作成日**: 2026年2月20日
**対象ブランチ**: feature/invoice-mvp

---

## 1. システム概要

### 1.1 目的
SES（システムエンジニアリングサービス）事業における契約管理・勤務表回収・請求書発行・入金管理を一元化する社内業務システム。

### 1.2 技術スタック

| 項目 | 技術 |
|------|------|
| フレームワーク | Django 4.2 |
| データベース | SQLite3 |
| フロントエンド | Bootstrap 5.3 + Bootstrap Icons |
| Excel操作 | openpyxl |
| PDF解析 | pdfplumber |
| AI連携 | OpenAI API（勤務表パース補助） |
| 認証 | Django標準認証 |
| デプロイ先 | VPS (85.131.249.73) / ドメイン: itfl-kanri.jp |

### 1.3 プロジェクト構成

```
itfl_app/
├── office_system/          # Djangoプロジェクト設定
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── system_app/             # メインアプリケーション
│   ├── models.py           # データモデル（14モデル）
│   ├── views.py            # ビュー（FBV: 関数ベースビュー）
│   ├── forms.py            # フォーム定義
│   ├── admin.py            # Django Admin設定
│   ├── urls.py             # URLルーティング
│   ├── services/           # ビジネスロジック層
│   │   ├── contracts.py
│   │   ├── invoice_calculator.py
│   │   ├── invoicing.py
│   │   ├── invoice_finalize.py
│   │   ├── estimate_exporter.py
│   │   ├── excel_renderer.py
│   │   ├── email_service.py
│   │   ├── sync_service.py
│   │   ├── invoice_exporters/
│   │   │   └── excel.py
│   │   └── timesheet_parsers/
│   │       ├── xlsx_generic.py
│   │       ├── pdf_generic.py
│   │       └── ai_fallback.py
│   └── templates/          # HTMLテンプレート（24ファイル）
│       ├── base.html
│       ├── dashboard.html
│       ├── party_list.html
│       ├── assignment_detail.html
│       ├── assignment_edit.html
│       ├── contact_entity_form.html
│       ├── timesheet_dashboard.html
│       ├── timesheet_detail.html
│       ├── invoice_list.html
│       ├── invoice_detail.html
│       ├── ar_list.html
│       ├── 【研修用】【雛型】請求書_SES_ITFL.xlsx
│       ├── 【雛型】御見積書_ITFL.xlsx
│       └── ...
├── media/                  # アップロードファイル
├── db.sqlite3
├── requirements.txt
└── CLAUDE.md
```

---

## 2. データモデル

### 2.1 ER図（概念）

```
ContactEntity ──┬── EntityContactPerson ── ContactEmail
                │
Assignment ─────┤   (worker / sales_owner / upstream / downstream)
                │
ServiceContract ┘
                │
Timesheet ──────┤
                │
Invoice ────────┤── InvoiceLine
                │
InvoicePayment ─┘
```

### 2.2 モデル定義

#### 2.2.1 ContactEntity（連絡先エンティティ）
個人（PERSON）と法人（COMPANY）を統合管理する。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| kind | CharField(20) | "PERSON" or "COMPANY" |
| name | CharField(255) | 氏名 or 会社名 |
| email | EmailField | メールアドレス |
| phone | CharField(50) | 電話番号 |
| worker_type | CharField(50) | 種別（PERSON: フリーランス/BP/正社員/契約社員） |
| address | TextField | 会社住所（COMPANY） |
| mailing_address | TextField | 送付先住所（COMPANY） |
| company_phone | CharField(50) | 会社電話番号（COMPANY） |
| has_invoice_registration | BooleanField | インボイス登録済みフラグ |

#### 2.2.2 EntityContactPerson（担当者）
法人エンティティに紐づく担当者。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| corporate_entity | FK → ContactEntity | 所属法人 |
| name | CharField(255) | 担当者名 |
| email | EmailField | メールアドレス |
| phone | CharField(50) | 電話番号 |
| line_available | BooleanField | LINE連絡可 |

#### 2.2.3 ContactEmail（追加メールアドレス）
担当者に紐づく追加メールアドレス（複数対応）。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| contact_person | FK → EntityContactPerson | 担当者 |
| email | EmailField | メールアドレス |
| description | CharField(100) | 説明（例: 請求書送付用） |

#### 2.2.4 Assignment（アサインメント/案件）
人材の案件配置情報。上位（発注元）・下位（発注先）の商流を管理する。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| worker_entity | FK → ContactEntity | 作業者 |
| sales_owner_entity | FK → ContactEntity | 営業担当 |
| upstream_entity | FK → ContactEntity | 上位（発注元） |
| upstream_contact_person | FK → EntityContactPerson | 上位担当者 |
| downstream_entity | FK → ContactEntity | 下位（発注先） |
| downstream_contact_person | FK → EntityContactPerson | 下位担当者 |
| project_name | CharField(255) | 案件名 |
| order_period_start_ym | DateField | 発注期間開始 |
| order_period_end_ym | DateField | 発注期間終了 |
| is_active | BooleanField | 稼働中フラグ |
| notes | TextField | 備考 |

#### 2.2.5 ServiceContract（契約条件）
Assignment に紐づく契約条件。期間ごとに複数レコード可（単価改定対応）。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| assignment | FK → Assignment | アサインメント |
| valid_from | DateField | 契約開始日 |
| valid_to | DateField | 契約終了日（NULL=現行） |
| **上位契約** | | |
| unit_price | IntegerField | 月額単価 |
| is_fixed_fee | BooleanField | 固定報酬フラグ |
| travel_expense_included | BooleanField | 交通費込みフラグ |
| lower_limit_hour | Decimal(10,2) | 精算下限時間 |
| upper_limit_hours | Decimal(10,2) | 精算上限時間 |
| deduction_unit_price | IntegerField | 控除単価（円/h） |
| excess_unit_price | IntegerField | 超過単価（円/h） |
| settlement_unit_minutes | IntegerField | 精算時間単位（分） |
| upstream_payment_terms | IntegerField | 支払サイト（日数） |
| bank_holiday_handling | CharField(100) | 金融機関休業日対応 |
| upstream_timesheet_collection_method | CharField(100) | 勤務表回収手段 |
| **下位契約** | | |
| downstream_unit_price | IntegerField | 下位単価 |
| downstream_is_fixed_fee | BooleanField | 下位固定報酬 |
| downstream_lower_limit_hour | Decimal(10,2) | 下位精算下限 |
| downstream_upper_limit_hours | Decimal(10,2) | 下位精算上限 |
| downstream_deduction_unit_price | IntegerField | 下位控除単価 |
| downstream_excess_unit_price | IntegerField | 下位超過単価 |
| downstream_settlement_unit_minutes | IntegerField | 下位精算単位 |
| downstream_payment_terms | IntegerField | 下位支払サイト |
| downstream_bank_holiday_handling | CharField(100) | 下位休業日対応 |
| downstream_timesheet_collection_method | CharField(100) | 下位勤務表回収手段 |
| downstream_timesheet_due_day | PositiveSmallInt | 下位勤務表締め日（翌月N日） |

#### 2.2.6 Timesheet（勤務表）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| assignment | FK → Assignment | アサインメント |
| billing_ym | CharField(6) | 対象年月（YYYYMM） |
| status | CharField(10) | received / processed |
| file | FileField | 勤務表ファイル |
| original_filename | CharField(255) | 元ファイル名 |
| actual_hours | Decimal(10,2) | 実稼働時間 |
| travel_amount | Decimal(12,0) | 交通費 |
| parse_confidence | JSONField | パース信頼度メタデータ |
| invoice | FK → Invoice | 紐づく請求書 |
| notes | TextField | 備考 |

**制約**: assignment + billing_ym でユニーク

#### 2.2.7 Invoice（請求書ヘッダ）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| assignment | FK → Assignment | アサインメント |
| billing_ym | CharField(6) | 請求対象年月（YYYYMM） |
| status | CharField(10) | draft / final / sent / cancelled |
| invoice_number | CharField(50) | 請求書番号（ユニーク） |
| issue_date | DateField | 発行日 |
| due_date | DateField | 支払期日 |
| tax_rate | Decimal(4,2) | 税率（デフォルト: 0.10） |
| subtotal_amount | Decimal(12,0) | 小計 |
| tax_amount | Decimal(12,0) | 消費税額 |
| total_amount | Decimal(12,0) | 合計金額 |
| actual_hours | Decimal(10,2) | 実稼働時間 |

**制約**: assignment + billing_ym でユニーク

#### 2.2.8 InvoiceLine（請求書明細行）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| invoice | FK → Invoice | 請求書 |
| kind | CharField(20) | basic / excess / deduction / expense / adjustment |
| display_order | PositiveSmallInt | 並び順（10,20,30,40） |
| item_name | CharField(255) | 品名 |
| quantity | Decimal(10,2) | 数量 |
| unit_price | Decimal(12,0) | 単価 |
| amount | Decimal(12,0) | 金額（控除はマイナス） |

**制約**: invoice + display_order でユニーク

#### 2.2.9 InvoicePayment（入金レコード）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| invoice | FK → Invoice | 請求書 |
| paid_date | DateField | 入金日 |
| amount | Decimal(12,0) | 入金額 |
| note | TextField | メモ |
| created_by | FK → User | 登録者 |

**インデックス**: invoice, paid_date

#### 2.2.10 レガシーモデル

以下のモデルは旧仕様から残存しており、現在はAssignment/ServiceContractベースに移行済み。

- **Freelancer**: 旧・個人事業主マスタ
- **MonthlyProcess**: 旧・月次管理
- **LegacyTaskStatus**: 旧・月次タスクステータス
- **TaskStatus**: 旧・新月次タスクステータス
- **BusinessPartner**: 提携パートナー
- **BusinessCard**: 名刺管理
- **PurchaseOrder**: 注文書管理

---

## 3. 機能一覧

### 3.1 サイドバーメニュー構成

| 順序 | メニュー | URL | 説明 |
|------|---------|-----|------|
| 1 | ダッシュボード | /dashboard/ | KPI概要表示 |
| 2 | 契約管理 | /party/ | 人材・案件・契約の一覧/詳細/編集 |
| 3 | 勤務表回収 | /timesheets/ | 勤務表の月別管理 |
| 4 | 請求書 | /invoices/ | 請求書の月別管理 |
| 5 | 入金管理 | /ar/ | 入金消込の月別管理 |

---

### 3.2 ダッシュボード

**URL**: `/dashboard/?ym=YYYYMM`

月別のKPI概要を表示する。月ナビゲーション（前月/翌月）付き。

**表示項目**:

| KPI | 算出ロジック |
|-----|------------|
| 勤務表：未回収 | 稼働中Assignment数 − 当月Timesheet提出数 |
| 請求：未送付 | 当月Invoice で status が draft or final の件数 |
| 請求：入金待ち | 当月Invoice で status が sent の件数 |
| 入金：未入金 | 当月due_date の sent Invoice で paid_sum < total_amount の件数 |
| 契約終了30日以内 | valid_to が今日〜30日後のServiceContract数 |
| 契約終了60日以内 | valid_to が今日〜60日後のServiceContract数 |

---

### 3.3 契約管理

#### 3.3.1 一覧（party_list）

**URL**: `/party/`

**機能**:
- Assignment ベースで人材一覧を表示
- 名前検索、worker_type フィルタ、稼働中/終了切り替え
- 各行に氏名、種別、営業担当、現行単価、案件名、発注期間を表示
- 行クリックで詳細画面へ遷移

**現行契約の取得ロジック**:
```
valid_from が NULL or 今日以前 AND valid_to が NULL or 今日以降
→ valid_from 降順で先頭1件
```

#### 3.3.2 詳細（assignment_detail）

**URL**: `/assignment/<int:pk>/`

**表示セクション**:
1. **人材情報**: 氏名、種別、メール、電話
2. **案件情報**: 営業担当、案件名、発注期間
3. **上位契約情報**: 単価、契約期間、精算幅、控除/超過単価、精算単位、勤務表回収手段、支払サイト、金融機関休業日対応
4. **下位契約情報**: （下位単価が存在する場合のみ表示）
5. **上位（発注元）**: 会社名、電話、住所、送付先、担当者情報
6. **下位（発注先）**: 会社名、電話、住所、送付先、担当者情報、インボイス登録状態
7. **備考**

**アクション**:
- 見積書Excelダウンロード
- 編集画面へ遷移
- 一覧に戻る

#### 3.3.3 新規登録（contact_entity_create）

**URL**: `/party/new/`

人材（ContactEntity）+ Assignment + ServiceContract を一括登録するフォーム。
上位/下位の会社・担当者も同時に作成可能。
担当者メールアドレスは動的フィールド（JavaScript）で複数追加可能。

#### 3.3.4 編集（assignment_edit）

**URL**: `/assignment/<int:pk>/edit/`

新規登録と同じフォームを使い、既存データを初期値として表示。
各エンティティの更新・新規作成を条件分岐で処理する。

#### 3.3.5 見積書エクスポート

**URL**: `/assignment/<int:assignment_id>/estimate-xlsx/`

Excel雛型テンプレート（`【雛型】御見積書_ITFL.xlsx`）にセルを埋め込んでダウンロード。

**埋め込みセル**:

| セル | 内容 |
|------|------|
| G2 | 発行日（YYYY年M月D日） |
| A5 | 宛先（クライアント名　御中） |
| A7 | ご担当 |
| A12 | 甲乙表記 |
| C13 | 業務名 |
| C14 | 契約形態（SES） |
| C15 | 作業期間 |
| C19 | 作業者名 |
| D20 | 金額（税抜） |
| C21 | 精算有無 |
| C22 | 精算単位 |
| C23 | 超過単価 |
| C24 | 控除単価 |
| C25 | 支払条件 |

**支払条件の計算ロジック**:
```
days ≤ 30 → 翌月{days}日
days > 30 → 翌々月{days-30}日
day == 30 → 末日
```

---

### 3.4 勤務表回収

#### 3.4.1 ダッシュボード（timesheet_dashboard）

**URL**: `/timesheets/?ym=YYYYMM`

**機能**:
- 月別ナビゲーション（前月/翌月）
- 稼働中の全Assignmentを一覧表示
- 各行にステータス（未回収/受領済/請求書生成済）を表示
- 勤務表締め日超過の場合は「期限超過」バッジを表示
- 未回収件数/全件数のサマリ
- アップロードフォーム（案件選択 + ファイル）

#### 3.4.2 アップロード（timesheet_upload）

**URL**: `/timesheets/upload/` (POST)

**処理フロー**:
1. ファイル受領（XLSX/PDF対応）
2. 一時ファイルに保存してパーサ実行
   - XLSX → `xlsx_generic.py`
   - PDF → `pdf_generic.py`
3. AIフォールバック補助（`ai_fallback.py`）
4. パース結果から actual_hours, travel_amount, billing_ym を抽出
5. parse_confidence メタデータ（セル位置、信頼度、エビデンス）を構築
6. ファイル名を `{ym}_{worker名}_{案件名}.{ext}` に変換
7. Timesheet レコードを create/update
8. 元のダッシュボードへリダイレクト

#### 3.4.3 詳細（timesheet_detail）

**URL**: `/timesheets/<int:pk>/`

**表示内容**:
- 勤務表メタ情報（ステータス、対象年月、実稼働時間、交通費）
- パース信頼度の表示（confidence, evidence, cell/page情報）
- Excelファイルの場合：HTML変換プレビュー + ハイライトセル表示
- PDFファイルの場合：インラインビューア + ハイライト位置情報
- 手動編集フォーム（actual_hours, travel_amount, notes）
- 請求書生成ボタン

#### 3.4.4 請求書生成（timesheet_generate_invoice）

**URL**: `/timesheets/<int:pk>/generate-invoice/` (POST)

Timesheetの actual_hours を元に Invoice ドラフトを自動生成する。
生成後は Timesheet.status を `processed` に更新し、invoice FK を設定。

---

### 3.5 請求書管理

#### 3.5.1 一覧（invoice_list）

**URL**: `/invoices/?ym=YYYYMM`

**機能**:
- 月別ナビゲーション
- 当月の全請求書を一覧表示
- 送付済/全件数のサマリ
- ステータスバッジ（下書き/確定/送付済/取消）
- アップロードフォーム（勤務表からではなく直接作成）

#### 3.5.2 詳細（invoice_detail）

**URL**: `/invoices/<int:invoice_id>/`

**Excel雛型レイアウトを再現した表示**:
- ヘッダ: 請求書番号、発行日、支払期日
- 明細テーブル: 品名、数量、単価、金額
- 小計、消費税、税込合計、交通費、請求合計
- 契約条件パネル（`<details>` 折りたたみ）

**アクション**:
- 保存（ヘッダ・明細行・交通費の手動編集）
- 再計算（契約条件と実稼働時間から明細行を再生成）
- Excelエクスポート
- 確定

#### 3.5.3 確定（invoice_finalize）

**URL**: `/invoices/<int:invoice_id>/finalize/` (POST)

**処理**:
1. status が draft でなければエラー
2. issue_date を設定（未設定なら今日）
3. due_date を設定（未設定なら契約の支払サイトから計算）
4. invoice_number を設定（未設定なら自動採番）
5. status を `final` に変更

#### 3.5.4 送付済トグル（invoice_toggle_sent）

**URL**: `/invoices/<int:invoice_id>/toggle-sent/` (POST)

status が `sent` ⇔ `draft` を切り替える。

#### 3.5.5 Excelエクスポート（invoice_export_xlsx）

**URL**: `/invoices/<int:invoice_id>/export-xlsx/`

Excel雛型テンプレート（`【研修用】【雛型】請求書_SES_ITFL.xlsx`）にセルを埋め込み。

**埋め込みセル**:

| セル | 内容 |
|------|------|
| A4 | 宛先（上位会社名） |
| H2 | 請求書番号 |
| F5 | 発行日 |
| A12 | 支払期日 |
| B12 | 曜日 |
| A16-G16 | 基本行（品名、数量、単価、金額） |
| A17 | 月分表示 |
| C18-G18 | 超過行 |
| C19-G19 | 控除行 |
| G20 | 小計 |
| G21 | 消費税 |
| G22 | 税込合計 |
| G25 | 交通費 |
| G27 | 請求合計 |
| E14 | 合計金額（ヘッダ） |
| H14 | 消費税（ヘッダ） |

---

### 3.6 入金管理

#### 3.6.1 メイン画面（ar_list）

**URL**: `/ar/?ym=YYYYMM`

**機能**:
- 月別ナビゲーション（支払期日月ベース）
- `status=sent` の請求書のうち、当月 due_date のものを一覧表示
- フィルタ: 取引先、状態（全件/入金済/一部入金/未入金/期限超過）
- サマリカード4枚: 請求合計、入金済、未入金額、完了件数

**各行の表示**:
- 作業者名、取引先名、金額、支払期日
- 入金状態バッジ: 入金済（緑）/ 一部入金（黄）/ 未入金（赤）/ 期限超過（赤+太字）

**入金パネル**（請求書選択時）:
- 請求書情報（金額、支払期日、入金済合計、残額）
- 入金登録フォーム（入金日、金額、メモ）
- 入金履歴テーブル（日付、金額、メモ、登録者、削除ボタン）

#### 3.6.2 入金登録（ar_payment_create）

**URL**: `/ar/invoices/<int:invoice_id>/payments/` (POST)

**バリデーション**:
- 入金日: 必須、日付形式
- 入金額: 必須、0より大きい
- 入金額が残額を超えていないこと

**処理**: InvoicePayment レコードを作成（`@transaction.atomic`）

#### 3.6.3 入金削除（ar_payment_delete）

**URL**: `/ar/payments/<int:payment_id>/delete/` (POST)

物理削除（`@transaction.atomic`）。削除後は元の請求書選択状態を維持してリダイレクト。

---

## 4. ビジネスロジック

### 4.1 請求書計算ロジック

**ファイル**: `services/invoice_calculator.py`

#### 明細行の生成（calculate_invoice_lines）

```
1. 基本行: 月額単価 × 1 = 月額単価
2. 超過行: (実稼働 - 上限) を精算単位で切り捨て → × 超過単価（ROUND_DOWN）
3. 控除行: (下限 - 実稼働) を精算単位で切り捨て → × 控除単価（マイナスで保存, ROUND_DOWN）
4. 交通費行: 交通費込みでなければ実費
```

#### 集計（recalculate_totals）

```
小計 = Σ(basic + excess + deduction)  ※交通費は除外
消費税 = 小計 × 税率（切り捨て: ROUND_DOWN）
合計 = 小計 + 消費税 + 交通費
```

#### 支払期日の計算（default_due_date）

```
翌月1日 + upstream_payment_terms（日数）
terms未設定 → 翌月末日
```

#### 請求書番号の採番（generate_invoice_number）

```
{YYYYMM}{A, B, C, ...}
同月の既存番号数でアルファベットを決定
例: 202602A, 202602B, ...
```

### 4.2 契約取得ロジック

**ファイル**: `services/contracts.py`

billing_ym を基準に有効な契約を取得:
```
valid_from が NULL or billing_month 以前
AND valid_to が NULL or billing_month 以降
→ valid_from 降順で先頭1件
```

### 4.3 請求書生成フロー

**ファイル**: `services/invoicing.py`

```
1. parsed dict から billing_ym, actual_hours, travel_amount を解決
2. 契約取得（get_active_contract）
3. Invoice を get_or_create（assignment + billing_ym でユニーク）
4. 既存 Invoice が draft 以外ならエラー
5. 明細行を計算（calculate_invoice_lines）
6. 全明細行を削除→再作成
7. ヘッダ値を設定（番号、発行日、期日）
8. 集計再計算（recalculate_totals）
```

### 4.4 請求書確定フロー

**ファイル**: `services/invoice_finalize.py`

```
1. SELECT FOR UPDATE で排他制御
2. status が draft でなければエラー
3. issue_date 設定（未設定→今日）
4. due_date 設定（未設定→支払サイトから計算）
5. invoice_number 設定（未設定→自動採番）
6. status を final に変更
```

---

## 5. URLルーティング

### 5.1 プロジェクトルート（office_system/urls.py）

| パス | 説明 |
|------|------|
| /admin/ | Django Admin |
| / | system_app URLに委譲 |
| /media/... | メディアファイル配信 |
| /static/... | 静的ファイル配信 |

### 5.2 アプリケーション（system_app/urls.py）

| パス | ビュー | 名前 |
|------|--------|------|
| / | index | index |
| /dashboard/ | dashboard | dashboard |
| /party/ | party_list | party_list |
| /party/new/ | contact_entity_create | contact_entity_create |
| /assignment/\<pk\>/ | assignment_detail | assignment_detail |
| /assignment/\<pk\>/edit/ | assignment_edit | assignment_edit |
| /assignment/\<id\>/estimate-xlsx/ | estimate_export_xlsx | estimate_export_xlsx |
| /timesheets/ | timesheet_dashboard | timesheet_dashboard |
| /timesheets/upload/ | timesheet_upload | timesheet_upload |
| /timesheets/\<pk\>/ | timesheet_detail | timesheet_detail |
| /timesheets/\<pk\>/download/ | timesheet_download | timesheet_download |
| /timesheets/\<pk\>/view/ | timesheet_view_inline | timesheet_view_inline |
| /timesheets/\<pk\>/generate-invoice/ | timesheet_generate_invoice | timesheet_generate_invoice |
| /invoices/ | invoice_list | invoice_list |
| /invoices/upload/ | invoice_upload | invoice_upload |
| /invoices/\<id\>/ | invoice_detail | invoice_detail |
| /invoices/\<id\>/finalize/ | invoice_finalize_view | invoice_finalize |
| /invoices/\<id\>/export-xlsx/ | invoice_export_xlsx | invoice_export_xlsx |
| /invoices/\<id\>/toggle-sent/ | invoice_toggle_sent | invoice_toggle_sent |
| /ar/ | ar_list | ar_list |
| /ar/invoices/\<id\>/payments/ | ar_payment_create | ar_payment_create |
| /ar/payments/\<id\>/delete/ | ar_payment_delete | ar_payment_delete |
| /login/ | LoginView | login |
| /logout/ | LogoutView | logout |

**レガシーURL**（旧機能、現在も動作）:

| パス | 説明 |
|------|------|
| /users/ | ユーザー管理 |
| /freelancers/ | 個人事業主CRUD |
| /monthly/ | 月次管理 |
| /purchase-orders/ | 注文書管理 |
| /partners/ | 提携パートナー |
| /business-cards/ | 名刺管理 |

---

## 6. 認証・認可

| 対象 | 方式 |
|------|------|
| 全ビュー（index, login除く） | `@login_required` |
| ユーザー作成 | `@staff_member_required` |
| ユーザー編集 | 自分自身 or `is_superuser` |
| Django Admin | `is_staff = True` |

**認証フロー**:
- 未認証 → `/login/` にリダイレクト（`LOGIN_URL = '/login/'`）
- ログイン成功 → `/dashboard/` にリダイレクト（`LOGIN_REDIRECT_URL`）
- ログアウト → `/login/` にリダイレクト（`LOGOUT_REDIRECT_URL`）

---

## 7. 設定（settings.py）

### 7.1 重要な設定値

| 設定 | 値 | 備考 |
|------|-----|------|
| USE_THOUSAND_SEPARATOR | True | テンプレート出力が自動カンマ区切りになる |
| NUMBER_GROUPING | 3 | |
| LANGUAGE_CODE | ja | 日本語化 |
| TIME_ZONE | UTC | |
| DEFAULT_AUTO_FIELD | BigAutoField | |
| SECRET_KEY | 環境変数 | .envから読み込み |
| DEBUG | 環境変数 | .envから読み込み |

### 7.2 USE_THOUSAND_SEPARATOR に関する注意事項

`USE_THOUSAND_SEPARATOR = True` により、テンプレートで数値を出力するとカンマ区切りになる。

**影響と対策**:
- `<input type="number">` はカンマを受け付けない → `{% localize off %}` で囲む
- 年表示（例: 2026）が「2,026」になる → `{% localize off %}{{ year }}{% endlocalize %}`
- 金額入力は `type="text" inputmode="numeric"` + サーバー側 `replace(',', '')`

---

## 8. 業務フロー

### 8.1 月次請求フロー

```
1. [契約管理] 人材・契約情報を登録
          ↓
2. [勤務表回収] 勤務表ファイルをアップロード
          ↓  自動パース（Excel/PDF + AI補助）
3. [勤務表詳細] パース結果を確認・手動修正
          ↓  「請求書生成」ボタン
4. [請求書詳細] ドラフト確認・手動修正・再計算
          ↓  「確定」ボタン
5. [請求書一覧] Excelエクスポート → クライアントへ送付
          ↓  「送付済」トグル
6. [入金管理] 入金確認・消込登録
```

### 8.2 見積書生成フロー

```
1. [契約管理 > 詳細] 「見積書」ボタンをクリック
          ↓
2. 契約情報（単価、精算条件、支払条件）をExcel雛型に埋め込み
          ↓
3. ダウンロード
```

---

## 9. マイグレーション履歴

| 番号 | 内容 |
|------|------|
| 0001 | 初期モデル（Freelancer, MonthlyProcess, ContactEntity, Assignment, ServiceContract等） |
| 0002 | Invoice, InvoiceLine, Timesheet 追加 |
| 0003 | Invoice.actual_hours 追加 |
| 0004 | ServiceContract.downstream_timesheet_due_day 他追加 |
| 0005 | InvoicePayment 追加 |

---

## 10. 外部依存

### 10.1 主要パッケージ

| パッケージ | 用途 |
|-----------|------|
| django | Webフレームワーク |
| openpyxl | Excelファイル操作 |
| pdfplumber | PDF勤務表パース |
| openai | AI補助（勤務表パース強化） |
| python-dotenv | 環境変数読み込み |

### 10.2 CDN

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| Bootstrap CSS | 5.3.0 | UIフレームワーク |
| Bootstrap Icons | 1.10.5 | アイコン |
| Bootstrap JS | 5.3.0 | ツールチップ等 |
| Noto Serif JP | Google Fonts | サイドバーブランドフォント |

---

## 11. 既知の制約・今後の改善候補

1. **SQLite**: 同時書き込みに弱い。本番運用ではPostgreSQLへの移行を推奨
2. **勤務表パーサ**: 汎用パーサのため、特殊フォーマットでは信頼度が低い場合がある
3. **入金管理**: 物理削除のみ（論理削除・監査ログ未実装）
4. **レガシーモデル**: Freelancer, BusinessPartner等はAssignment系に移行済みだが、旧URLは残存
5. **テスト**: 自動テスト未整備
6. **メディアファイル**: `re_path` で直接配信（本番ではNginx推奨）
7. **タイムゾーン**: settings.py で UTC のまま（Asia/Tokyo が望ましい）
