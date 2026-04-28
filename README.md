# PIMS-NOTIFICATION

FastAPI microservice that exposes **Email**, **SMS** and **OTP** APIs for the
PIMS platform. Providers, ports, credentials and OTP rules are all driven
from environment variables — no code change is needed to switch SMTP to
SendGrid, or Twilio to MSG91.

## Project structure

```
PIMS-NOTIFICATION/
├── app/
│   ├── main.py                 # FastAPI application factory
│   ├── config/                 # .env loader (pydantic-settings)
│   ├── middleware/             # Request-ID logging + global error handler
│   ├── controllers/            # Thin orchestration layer
│   ├── routes/                 # API URL definitions (== "urls")
│   ├── services/               # Provider integrations (Email, SMS, OTP)
│   ├── schemas/                # Pydantic request/response models
│   └── utilities/              # Logger and shared helpers
├── tests/                      # Pytest tests (TestClient based)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env / .env.example
└── README.md
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit values
uvicorn app.main:app --reload --port 8000
```

## Run with Docker

```bash
docker build -t pims-notification:latest .
docker run --rm -p 8000:8000 --env-file .env pims-notification:latest
# or
docker compose up --build
```

## API documentation (Swagger / ReDoc)

| URL                     | Purpose                                  |
|-------------------------|------------------------------------------|
| `GET /docs`             | Interactive Swagger UI                   |
| `GET /redoc`            | ReDoc reference                          |
| `GET /openapi.json`     | OpenAPI 3 schema                         |
| `GET /api/v1/health`    | Liveness probe                           |

## Endpoints

| Method | Path                                    | Purpose                          |
|--------|-----------------------------------------|----------------------------------|
| POST   | `/api/v1/notifications/email/send`      | Send a transactional email       |
| POST   | `/api/v1/notifications/sms/send`        | Send an SMS                      |
| POST   | `/api/v1/notifications/otp/send`        | Generate and send an OTP         |
| POST   | `/api/v1/notifications/otp/verify`      | Verify an OTP                    |

## Environment variables

See `.env.example` for the full list. The most important ones:

| Variable          | Allowed values            | Description                          |
|-------------------|---------------------------|--------------------------------------|
| `EMAIL_PROVIDER`  | `smtp`, `sendgrid`        | Selects the email backend            |
| `SMS_PROVIDER`    | `twilio`, `msg91`, `mock` | Selects the SMS backend              |
| `APP_PORT`        | integer                   | Public port (mapped by Docker)       |
| `OTP_LENGTH`      | 4-10                      | OTP digit length                     |
| `OTP_TTL_SECONDS` | integer                   | OTP validity window                  |

## Tests

```bash
pip install -r requirements.txt
pytest -q
```
