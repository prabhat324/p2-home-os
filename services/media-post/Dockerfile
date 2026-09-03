FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg python3 python3-pip fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY pipeline.py project.json ./
ENTRYPOINT ["python3","/app/pipeline.py"]

