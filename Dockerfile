FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY portfolio ./portfolio
COPY pyproject.toml LICENSE .
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home appuser
USER 10001
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "/dev/null", "portfolio:create_app()"]

