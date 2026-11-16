FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
COPY data/requirements.txt data/requirements.txt
COPY infrastructure/demo/requirements.txt infrastructure/demo/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY data/ data/
COPY scripts/load_to_supabase.py scripts/load_to_supabase.py
RUN python -m data.src.etl.nasa_etl
RUN useradd --uid 10001 --create-home pyrogravity
USER pyrogravity
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
