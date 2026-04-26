# --- Build stage ---
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .

# Install Python deps to a user-local prefix so we can copy them into the runtime image.
RUN pip install --no-cache-dir --user --no-warn-script-location -r requirements.txt


# --- Runtime stage ---
FROM python:3.12-slim

# Minimal runtime libs (opencv-python-headless + libav need glib at runtime).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Bring in the Python deps installed in the builder.
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY . .

RUN mkdir -p /app/generated

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
