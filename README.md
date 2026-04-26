# DrawClip API

HTTP API for generating stylised videos from images, using a job-based workflow.
Designed to host **multiple styles** (whiteboard sketch, and others to come)
under a single shared job system, with **per-user isolation**.

## Run

### With Docker (recommended for production / homelab)

```bash
docker compose up -d --build
docker compose logs -f          # follow logs
docker compose down              # stop
```

The container exposes port `8000` and persists generated videos in `./generated/`.
A health-check (`GET /health`) runs every 30 s.

### Without Docker (local dev)

```bash
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- **Swagger UI** → http://localhost:8000/docs
- **ReDoc** → http://localhost:8000/redoc
- **OpenAPI schema** → http://localhost:8000/openapi.json

## Authentication (temporary)

Every request that touches jobs (`/generate/*`, `/jobs/*`) requires an
`X-User-Id` HTTP header. The value must be a **valid UUID string**.
Ownership is scoped to that UUID — each user only sees and downloads their own jobs.

> ⚠️ This is **not** a real auth mechanism: anyone who knows a UUID can claim it.
> It will be replaced by API keys / JWT once the SaaS has a frontend and a
> user database.

For local development, use this seed UUID (or any other valid UUID):

```
3e271a2a-c636-40d6-bdfe-b47e8c080fad
```

```bash
curl -H "X-User-Id: 3e271a2a-c636-40d6-bdfe-b47e8c080fad" http://localhost:8000/jobs
```

To generate a new one:

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

In Swagger UI, expand a route's "Parameters" section to fill the header field.

## Workflow

1. `POST /generate/{style}` — submit an image with style-specific params, get a `job_id`.
2. `GET /jobs/{job_id}` — poll the status (`pending → running → done | error`) and progress (0–100).
3. `GET /jobs/{job_id}/download` — download the generated mp4 once `status` is `done`.

The status response includes an absolute `download_url` once the job is `done`, plus the
`style` that was used.

## Limits

- **20 seconds** maximum video duration (`total_image_duration`)
- **10 jobs per user** kept; older jobs (and their files) are evicted automatically
  when that user submits a new job. Other users' jobs are unaffected.
- **2 concurrent renderings** server-wide (thread pool size).

## Endpoints

| Method | Path                          | User header? | Description                         |
|--------|-------------------------------|:------------:|-------------------------------------|
| POST   | `/generate/whiteboard`        | required     | Submit a whiteboard-style job       |
| GET    | `/jobs`                       | required     | List the caller's jobs              |
| GET    | `/jobs/{job_id}`              | required     | Get status (404 if not yours)       |
| GET    | `/jobs/{job_id}/download`     | required     | Download mp4 (404 if not yours)     |
| GET    | `/styles`                     | —            | List available styles               |
| GET    | `/health`                     | —            | Liveness probe                      |

## Available styles

### `whiteboard`

Whiteboard-style sketch animation drawn by a hand cursor.

| Field                  | Default | Description                                                            |
|------------------------|---------|------------------------------------------------------------------------|
| `image`                | —       | File: png / jpg / jpeg / webp                                          |
| `total_image_duration` | 10      | Total video length in seconds (1–20)                                   |
| `writing_duration`     | 6       | Seconds the hand spends drawing (1–20, must be ≤ `total_image_duration`) |
| `ratio`                | auto    | `auto` \| `16:9` \| `9:16` \| `1:1` \| `4:3`                            |
| `draw_hand`            | true    | Show the drawing-hand cursor                                            |
| `color_while_drawing`  | false   | Draw with original colors (true) or as a black & white sketch          |

## Project layout

```
.
├── main.py               FastAPI app, generic routes, mounts style routers
├── auth.py               X-User-Id header dependency (temporary)
├── jobs.py               JobManager (UUIDv7, thread pool, per-user FIFO eviction)
├── uploads.py            upload validation helper
├── styles/
│   ├── __init__.py       registry of available styles
│   ├── base.py           Style ABC + StyleParams
│   └── whiteboard/
│       ├── style.py      WhiteboardStyle + WhiteboardParams
│       ├── render.py     OpenCV/NumPy/PyAV rendering engine
│       ├── routes.py     POST /generate/whiteboard
│       └── assets/       drawing-hand.png, hand-mask.png
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── LICENSE
└── README.md
```

## Adding a new style

1. Copy `styles/whiteboard/` to `styles/<new_style>/`.
2. In `<new_style>/style.py`, replace the body of `render()` with your engine, and
   define your `<NewStyle>Params` Pydantic model.
3. In `<new_style>/routes.py`, expose the form fields you want and call `request.app.state.jobs.submit(user_id, style, params, tmp_input)`.
4. Register the style in `styles/__init__.py` (one line in `_REGISTRY`).
5. Mount the router in `main.py` (one `app.include_router(...)` line).

The job system, per-user isolation, status polling, download route, and eviction are shared.

## Example

```bash
USER="3e271a2a-c636-40d6-bdfe-b47e8c080fad"

# Submit
JOB=$(curl -s -X POST http://localhost:8000/generate/whiteboard \
  -H "X-User-Id: $USER" \
  -F "image=@./my_image.png" \
  -F "total_image_duration=10" \
  -F "writing_duration=6" \
  -F "ratio=16:9" \
  -F "color_while_drawing=true" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")

# Poll
curl -s -H "X-User-Id: $USER" http://localhost:8000/jobs/$JOB

# Download once status=done
curl -s -H "X-User-Id: $USER" http://localhost:8000/jobs/$JOB/download -o output.mp4
```
