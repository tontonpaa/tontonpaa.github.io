# ★ 変更: 3.14.0a7 (不安定なアルファ版) から 3.12 (安定版) に変更
FROM python:3.12-bookworm

# ビルド時に不要な.pycファイルが生成されるのを防ぎ、ログ出力を即時反映させる推奨設定
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★ 追加: yarl/aiohttp のロケールエラー(ValueError)対策
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# 1. 必要なパッケージをインストールし、ロケール(en_US.UTF-8)を生成
RUN apt-get update && \
    apt-get install -y locales && \
    sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    rm -rf /var/lib/apt/lists/*

# 2. Pythonが使用する環境変数としてUTF-8を明示的に設定
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV PYTHONUTF8 1
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# アプリケーションの作業ディレクトリを設定
WORKDIR /app

# 2. 依存関係ファイルだけを先にコピー（キャッシュ効率のため）
COPY requirements.txt .

# 3. 依存関係をインストール
RUN pip install --no-cache-dir -r requirements.txt

# 4. アプリケーションのコード全体をコピー
COPY . .

# 5. 起動コマンドを修正
# ファイル名はご自身のものに合わせてください
CMD ["python", "main.py"]
