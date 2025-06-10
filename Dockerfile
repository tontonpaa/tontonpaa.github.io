FROM python:3.14.0a7-bookworm

# ビルド時に不要な.pycファイルが生成されるのを防ぎ、ログ出力を即時反映させる推奨設定
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# アプリケーションの作業ディレクトリを設定
WORKDIR /app

# 2. 依存関係ファイルだけを先にコピー（キャッシュ効率のため）
COPY requirements.txt .

# 3. 依存関係をインストール
RUN pip install --no-cache-dir -r requirements.txt

# 4. アプリケーションのコード全体をコピー
COPY . .

# 5. 起動コマンドを修正（仮想環境は不要なため直接pythonを指定）
# ファイル名はご自身のものに合わせてください
CMD ["python", "main.py"]
