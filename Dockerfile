FROM python:3.14.0a7-bookworm

WORKDIR /app

RUN python -m venv venv
RUN . venv/bin/activate
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["venv/bin/python", "main.py"]