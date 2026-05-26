# AI Stack – Complete Setup Guide
*Written for someone who has never set up AI infrastructure before.*

---

## What you're building

You have a server with 30 GB RAM and 8 CPU cores. By the end of this guide, the following will be running in Docker containers on that server:

| Service | What it does | RAM used |
|---|---|---|
| **vLLM** | Runs your LLM (Llama / Qwen) | ~6–10 GB |
| **Embedding** | Turns text into numbers for search | ~1.5 GB |
| **Qdrant** | Stores and searches those numbers | ~0.5 GB |
| **PaddleOCR** | Reads text from images/PDFs | ~1 GB |
| **FastAPI** | Your team's application | ~0.5 GB |
| **Total** | | ~10–14 GB of 30 GB |

PostgreSQL and NFS/S3 stay on their existing servers — we just connect to them.

---

## PART 1 — Prepare your server

### Step 1.1 – Install Docker

SSH into your server, then run these commands one at a time.

```bash
# Remove old versions of Docker if any exist
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Allow your user to run Docker without sudo (log out and back in after this)
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker works
docker run --rm hello-world
```

You should see "Hello from Docker!" — that means Docker is working.

### Step 1.2 – Verify Docker Compose is available

```bash
docker compose version
# Should print: Docker Compose version v2.x.x
```

If it says "command not found", install it:
```bash
sudo apt-get install -y docker-compose-plugin
```

### Step 1.3 – Check your RAM

```bash
free -h
```

Look for the "total" column. You need at least 20 GB shown here.

### Step 1.4 – Mount your NFS share (skip if using S3)

If your files are on an NFS server:
```bash
# Install NFS client tools
sudo apt-get install -y nfs-common

# Create a mount point
sudo mkdir -p /mnt/nfs

# Mount it (replace with your NFS server IP and share path)
sudo mount -t nfs YOUR_NFS_SERVER_IP:/your/share/path /mnt/nfs

# Test that it works
ls /mnt/nfs

# Make it auto-mount on reboot (add this line to /etc/fstab)
echo "YOUR_NFS_SERVER_IP:/your/share/path  /mnt/nfs  nfs  defaults  0  0" | sudo tee -a /etc/fstab
```

---

## PART 2 – Set up the project files

### Step 2.1 – Copy the stack files to your server

Create the working directory:
```bash
mkdir -p ~/ai-stack
cd ~/ai-stack
```

Copy all files from this bundle into `~/ai-stack/`. The structure should be:
```
~/ai-stack/
├── docker-compose.yml
├── deploy.sh
├── stack.sh
├── .env.example
└── scripts/
    ├── paddle_server.py
    └── services_client.py
```

Make the shell scripts executable:
```bash
chmod +x deploy.sh stack.sh
```

### Step 2.2 – Create your `.env` file

```bash
cp .env.example .env
nano .env   # or use vim, or any text editor
```

Fill in each value. The most important ones:

**HuggingFace token** (needed to download Llama — it's free):
1. Go to https://huggingface.co and create a free account
2. Go to Settings → Access Tokens → New token (read access is enough)
3. Paste it as `HF_TOKEN=hf_...`

**LLM Model** — uncomment the line for the model you want. For a first test, use `Qwen/Qwen3-4B` (smallest, downloads fastest):
```
LLM_MODEL=Qwen/Qwen3-4B
```

**Database URL** — point this at your existing PostgreSQL:
```
DATABASE_URL=postgresql://myuser:mypassword@192.168.1.50:5432/mydb
```

**File storage** — choose NFS or S3, fill in the relevant fields.

---

## PART 3 – First-time startup

### Step 3.1 – Start Qdrant first (quick test)

Before starting everything, let's make sure Docker networking works:
```bash
./stack.sh up qdrant
sleep 5
curl http://localhost:6333/healthz
# Should print: {"title":"qdrant - version x.x.x","version":"x.x.x"}
```

### Step 3.2 – Start the embedding service

```bash
./stack.sh up embedding
# This downloads the BAAI model (~600 MB) on first run
# Watch it download:
./stack.sh logs embedding
# Wait until you see "Ready to serve"
```

Test it:
```bash
curl -X POST http://localhost:8001/embed \
  -H "Content-Type: application/json" \
  -d '{"inputs": "hello world"}'
# Should return a long list of numbers starting with [ 0.012, -0.345, ... ]
```

### Step 3.3 – Start vLLM (the LLM)

This will download the model (~4–8 GB depending on which you chose):
```bash
./stack.sh up vllm
./stack.sh logs vllm   # Watch the download progress
# Wait until you see "Application startup complete"
# This can take 5-15 minutes on first run
```

Test the LLM:
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-4B",
    "messages": [{"role": "user", "content": "Say hello in one sentence."}],
    "max_tokens": 50
  }'
# Should return a JSON response with the LLM's reply
```

### Step 3.4 – Start PaddleOCR

```bash
./stack.sh up paddleocr
./stack.sh logs paddleocr   # Watch pip install progress
# First run installs Python packages (~2-3 minutes)
```

Test OCR with a sample image:
```bash
# Download a test image
curl -o /tmp/test.jpg "https://www.w3schools.com/css/img_5terre.jpg"

curl -X POST http://localhost:8002/ocr \
  -F "file=@/tmp/test.jpg"
# Returns detected text blocks (may be empty for a scenery photo — that's fine)
```

### Step 3.5 – Full deploy (your FastAPI app)

Once you've filled in `REPO_URL` in `.env` with your team's git repository:
```bash
./deploy.sh
# This will:
# 1. Clone your repo
# 2. Build the Docker image
# 3. Start all services
# 4. Wait for health checks
```

---

## PART 4 – Day-to-day operations

### Checking status
```bash
./stack.sh status
```

### Viewing logs
```bash
./stack.sh logs fastapi      # Your app
./stack.sh logs vllm         # LLM server
./stack.sh logs qdrant       # Vector DB
./stack.sh logs embedding    # Embedding service
./stack.sh logs paddleocr    # OCR service
```

### Shutting down the entire stack
```bash
./stack.sh down
# This stops all containers. Your data (Qdrant vectors, model files) is kept safe.
```

### Starting back up
```bash
./stack.sh up
# Models are already cached, so this starts in ~1-2 minutes instead of 15+
```

### Deploying a new version of your FastAPI app
```bash
./deploy.sh
# Pulls latest code, rebuilds image, restarts app (other services keep running)
```

### Deploying a specific git branch
```bash
./deploy.sh --branch feature/my-new-feature
```

### Restart only the FastAPI app (without rebuilding)
```bash
./stack.sh restart fastapi
```

---

## PART 5 – Connecting to everything from your FastAPI code

Copy `scripts/services_client.py` into your FastAPI project. It has ready-to-use async functions for:

- `ask_llm(prompt)` — send a message to the LLM
- `embed_text(text)` — turn text into a search vector
- `qdrant_upsert(...)` — store a document in the vector DB
- `qdrant_search(...)` — find similar documents
- `ocr_image(bytes)` — extract text from an image
- `rag_answer(question)` — full RAG pipeline in one call

Environment variables your FastAPI app should read (already set in docker-compose.yml):
```
VLLM_BASE_URL=http://vllm:8000
EMBEDDING_URL=http://embedding:80
QDRANT_URL=http://qdrant:6333
OCR_URL=http://paddleocr:8002
DATABASE_URL=postgresql://...
```

Use `os.getenv("VLLM_BASE_URL")` etc. in your code — don't hardcode the URLs.

---

## PART 6 – Switching LLM models

Edit `.env`:
```bash
nano .env
# Change the LLM_MODEL line, uncomment a different model
```

Then restart vLLM:
```bash
./stack.sh restart vllm
./stack.sh logs vllm   # Watch it load the new model
```

---

## PART 7 – Troubleshooting

**"Container exits immediately"**
```bash
./stack.sh logs <service_name>
# Read the last few lines — the error is usually printed there
```

**"Out of memory" / services crashing**
- Reduce `LLM_MAX_CTX` in `.env` (try 2048)
- Reduce `VLLM_MEM_LIMIT` in `.env` (try 12g)
- Switch to a smaller model (Qwen3-4B uses ~3 GB vs Llama-8B at ~6 GB)

**"Cannot connect to database"**
- Check `DATABASE_URL` in `.env`
- Make sure your PostgreSQL server allows connections from this server's IP
- Test: `docker exec fastapi python -c "import psycopg2; psycopg2.connect('$DATABASE_URL')"`

**"Model not found on HuggingFace"**
- Some models (like Llama) require you to accept a license at huggingface.co
- Visit the model page, click "Agree and access", then re-run `./deploy.sh`

**"Qdrant API key errors"**
- If `QDRANT_API_KEY` is empty in `.env`, Qdrant runs without auth — this is fine
- If you set a key, all requests must include the `api-key` header (already handled in `services_client.py`)

**Reset everything and start fresh (DELETES ALL DATA)**
```bash
./stack.sh reset-volumes
./stack.sh up
```

---

## Quick Reference Card

| Task | Command |
|---|---|
| Start everything | `./stack.sh up` |
| Stop everything | `./stack.sh down` |
| Check status | `./stack.sh status` |
| View logs | `./stack.sh logs <service>` |
| Deploy new code | `./deploy.sh` |
| Deploy specific branch | `./deploy.sh --branch name` |
| Restart one service | `./stack.sh restart fastapi` |
| Test LLM | `curl -X POST http://localhost:8000/v1/chat/completions ...` |
| Test Qdrant | `curl http://localhost:6333/healthz` |
| Test Embedding | `curl -X POST http://localhost:8001/embed ...` |
| Test OCR | `curl -X POST http://localhost:8002/ocr -F file=@image.jpg` |
