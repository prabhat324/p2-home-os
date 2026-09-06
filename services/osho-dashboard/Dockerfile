FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends snmp \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

# The root-owned compute-02 deploy helper intentionally downloads a fixed,
# allowlisted file set. Pull source-controlled runtime overlays at build time
# so the helper does not need broader filesystem or sudo permissions.
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/server.py /app/server.py
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/storage_server.py /app/storage_server.py
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/power_server.py /app/power_server.py
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/live_power_server.py /app/live_power_server.py
# Local analytics.html is maintained in app/static so dashboard navigation stays consistent.
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/static/storage01.js /app/static/storage01.js
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/osho-dashboard/app/static/powergrid.js /app/static/powergrid.js
# Keep the GitHub runtime overlay authoritative; do not overwrite powergrid.js
# with the helper's older local build-context copy.
ADD https://raw.githubusercontent.com/prabhat324/p2-home-os/f15a496e91170a288c5dbdf38a5bf24d58cbce45/services/osho-dashboard/app/static/tst902.html /app/static/tst902.html

EXPOSE 8787

CMD ["uvicorn", "reviewmuse_server:app", "--host", "0.0.0.0", "--port", "8787"]
