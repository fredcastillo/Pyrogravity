FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
COPY data/requirements.txt data/requirements.txt
COPY infrastructure/demo/requirements.txt infrastructure/demo/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m data.src.etl.nasa_etl
RUN useradd --uid 10001 --create-home pyrogravity
USER pyrogravity
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
