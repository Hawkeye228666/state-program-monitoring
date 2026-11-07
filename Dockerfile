FROM python:3.12.15-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 monitor \
    && useradd --uid 10001 --gid monitor --no-create-home --shell /usr/sbin/nologin monitor
COPY . .
RUN mkdir -p /app/data /app/staticfiles \
    && POSTGRES_DB=build POSTGRES_APP_USER=build POSTGRES_APP_PASSWORD=build-only POSTGRES_HOST=unavailable python manage.py collectstatic --noinput \
    && chown -R 10001:10001 /app/data
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--no-control-socket", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
