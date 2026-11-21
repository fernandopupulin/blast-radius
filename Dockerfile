FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN pip install --no-cache-dir python-dateutil==4.0.0 pytz==2026.6 tzdata==2026.6
ADD upstream.tar.gz /upstream/
COPY selector.py impact.json.gz LICENSE-SQLGLOT query_probe.py query-checkpoints.json /app/
CMD ["python", "/app/selector.py"]
