開発環境の準備手順
1. Git clone
git clone git@github.com:itfl0801/itfl_app.git

2. ディレクトリ内に遷移
cd itfl_app

3. 仮想環境の作成と起動
python -m venv venv
もしエラーの場合
python3 -m venv venv

4. ライブラリのインストール
pip install -r requirements.txt
もしエラーの場合
pip3 install -r requirements.txt

5. DBのマイグレーション
python manage.py migrate

6.サーバー起動
python manage.py runserver

7. ブラウザでアクセス
http://127.0.0.1:8000/ にアクセスすれば表示できるはず。
もし400や404が表示される場合、ターミナルにログが表示されるので、エラー文言見て調べてみてください。

runserverを止める場合は、Macの場合"control" + Cで止まります。

