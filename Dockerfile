FROM python:3.12.9-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip cache purge && pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]