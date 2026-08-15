FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

# The root-owned compute-02 deploy helper intentionally downloads a fixed,
# allowlisted file set. Pull these source-controlled analytics assets at build
# time so the helper does not need broader filesystem or sudo permissions.
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/server.py /app/server.py
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/static/analytics.html /app/static/analytics.html

EXPOSE 8787

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8787"]
