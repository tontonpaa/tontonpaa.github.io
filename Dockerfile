FROM python:3.14.0a7-bookworm

WORKDIR /app

RUN python -m venv venv
ENV PATH="/app/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import discord; print(discord.__version__)"

COPY . .

CMD ["venv/bin/python", "main.py"]