FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY ai/pyproject.toml ./pyproject.toml
COPY ai/src/ ./src/
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home pyrogravity
USER pyrogravity
EXPOSE 8001
CMD ["uvicorn", "pyrogravity_ai.service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
