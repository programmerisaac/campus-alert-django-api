# CampusAlert — Django Backend

> Real-time emergency alert system for Covenant University.
> Built with Django, Django REST Framework, Celery, Redis, and PostgreSQL.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [Prerequisites](#5-prerequisites)
6. [Installation & Setup](#6-installation--setup)
7. [Environment Variables](#7-environment-variables)
8. [Database Setup](#8-database-setup)
9. [Running the Application](#9-running-the-application)
10. [API Endpoints Reference](#10-api-endpoints-reference)
11. [Authentication System](#11-authentication-system)
12. [Alert System](#12-alert-system)
13. [ML Classification Pipeline](#13-ml-classification-pipeline)
14. [WebSocket Support](#14-websocket-support)
15. [FCM Push Notifications](#15-fcm-push-notifications)
16. [Celery Background Tasks](#16-celery-background-tasks)
17. [Security](#17-security)
18. [Logging](#18-logging)
19. [Running Tests](#19-running-tests)
20. [Deployment](#20-deployment)

---

## 1. Project Overview

CampusAlert is a university-wide emergency notification system that delivers
time-critical alerts to students and staff at Covenant University. When an
administrator composes an alert, an AI/ML pipeline automatically classifies
its urgency level, and the system dispatches it through multiple delivery
channels simultaneously.

### What the backend does

- Authenticates users via Covenant University email addresses
- Classifies alert urgency automatically using an XGBoost ML model
  with keyword-based override for critical terms
- Dispatches alerts through Firebase Cloud Messaging (FCM) for internet
  delivery and WebSocket for campus LAN delivery
- Tracks per-user delivery and acknowledgement status
- Stores missed alerts for devices that were offline during dispatch
- Protects all endpoints with JWT authentication and brute-force lockout

### User Roles

| Role    | Email Domain                      | Capabilities                          |
|---------|-----------------------------------|---------------------------------------|
| Student | @stu.cu.edu.ng                    | Receive alerts, acknowledge, view feed|
| Staff   | @covenantuniversity.edu.ng        | Receive alerts, acknowledge, view feed|
| Admin   | @covenantuniversity.edu.ng        | All of the above + compose + view stats|

> Admins are manually promoted from staff accounts via the Django admin panel.
> They cannot self-register as admins.

---

## 2. System Architecture


┌─────────────────────────────────────────────────────────────────┐
│                        React Native App                         │
│              (Student / Staff / Admin mobile client)            │
└──────────────┬──────────────────────────────┬───────────────────┘
               │  HTTPS REST API              │  WebSocket (LAN)
               ▼                              ▼
┌──────────────────────────┐    ┌─────────────────────────────────┐
│   Django REST Framework  │    │   Django Channels (ASGI)        │
│   (HTTP API endpoints)   │    │   (WebSocket consumers)         │
└──────────┬───────────────┘    └─────────────┬───────────────────┘
           │                                  │
           ▼                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Django Core                               │
│   accounts │ alerts │ ml │ core                                  │
└──────┬───────────────┬──────────────────────┬────────────────────┘
       │               │                      │
       ▼               ▼                      ▼
┌────────────┐  ┌─────────────┐    ┌──────────────────┐
│ PostgreSQL │  │    Redis     │    │  Celery Worker   │
│ (primary   │  │ (cache +     │    │  (async tasks:   │
│  database) │  │  broker +    │    │   classify +     │
│            │  │  channels)   │    │   dispatch)      │
└────────────┘  └─────────────┘    └────────┬─────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │  Firebase FCM   │
                                   │  (push delivery)│
                                   └─────────────────┘





### Alert Delivery Flow



Admin composes alert
        │
        ▼
POST /api/v1/alerts/compose/
        │
        ▼
Celery task: classify_and_dispatch
        │
        ├──▶ ML Classifier (XGBoost / keyword override)
        │         │
        │         ▼
        │    Urgency assigned: critical | high | medium | low
        │
        ├──▶ FCM delivery (internet push notification)
        │
        ├──▶ WebSocket broadcast (campus LAN)
        │
        └──▶ DeliveryLog created per recipient




---

## 3. Technology Stack

| Component            | Technology                        | Version  |
|----------------------|-----------------------------------|----------|
| Web framework        | Django                            | 6.x      |
| REST API             | Django REST Framework             | 3.x      |
| Authentication       | djangorestframework-simplejwt     | 5.x      |
| Token blacklist      | simplejwt token_blacklist         | built-in |
| Brute-force protect  | django-axes                       | 6.x      |
| WebSocket            | Django Channels + Daphne          | 4.x      |
| Task queue           | Celery                            | 5.x      |
| Message broker       | Redis                             | 7.x      |
| Database             | PostgreSQL                        | 15+      |
| ML classification    | XGBoost + scikit-learn            | latest   |
| Push notifications   | Firebase Admin SDK (FCM)          | latest   |
| CORS                 | django-cors-headers               | 4.x      |
| Env management       | django-environ                    | 0.11+    |
| Filtering            | django-filter                     | 23+      |

---

## 4. Project Structure



website/                          ← Django project root
├── .env                          ← Secret environment variables (never commit)
├── .env.example                  ← Template showing all required env vars
├── manage.py                     ← Django management command entry point
├── README.md                     ← This file
│
├── website/                      ← Django project configuration package
│   ├── settings.py               ← All project settings
│   ├── urls.py                   ← Root URL configuration
│   ├── asgi.py                   ← ASGI entry point (HTTP + WebSocket)
│   ├── wsgi.py                   ← WSGI entry point (HTTP only)
│   └── celery.py                 ← Celery application instance
│
├── accounts/                     ← User authentication app
│   ├── models.py                 ← Custom User model with role + CU fields
│   ├── backends.py               ← Email-based authentication backend
│   ├── serializers.py            ← Registration, login, profile serializers
│   ├── views.py                  ← Auth API views (register, login, logout…)
│   ├── urls.py                   ← Account URL patterns
│   ├── admin.py                  ← Django admin registration
│   └── migrations/               ← Database migration files
│
├── alerts/                       ← Alert management app
│   ├── models.py                 ← Alert, DeliveryLog models
│   ├── serializers.py            ← Alert read/write serializers
│   ├── views.py                  ← Alert API views (feed, compose, ack…)
│   ├── urls.py                   ← Alert URL patterns
│   ├── consumers.py              ← Django Channels WebSocket consumer
│   ├── permissions.py            ← Custom DRF permissions (IsAdmin etc.)
│   ├── tasks.py                  ← Celery tasks (classify_and_dispatch)
│   ├── services/
│   │   ├── classifier.py         ← ML urgency classification logic
│   │   ├── delivery.py           ← Alert dispatch orchestrator
│   │   └── fcm.py                ← Firebase FCM HTTP v1 API wrapper
│   └── migrations/
│
├── ml/                           ← Machine learning model management app
│   ├── models.py                 ← MLModel registry (tracks trained models)
│   ├── data/                     ← Training datasets (CrisisLex T26 etc.)
│   └── ...
│
├── core/                         ← Shared utilities
│   ├── exceptions.py             ← Custom DRF exception handler
│   ├── models.py                 ← Abstract base models (timestamps etc.)
│   └── ...
│
└── logs/
    └── django.log                ← Application log file




---

## 5. Prerequisites

Before you begin, make sure the following are installed on your machine.

### Required software

| Software   | Version | Installation                              |
|------------|---------|-------------------------------------------|
| Python     | 3.11+   | https://python.org                        |
| PostgreSQL | 15+     | https://postgresql.org                    |
| Redis      | 7+      | https://redis.io (or via Docker)          |
| Git        | any     | https://git-scm.com                       |

### Optional but recommended

| Software      | Purpose                              |
|---------------|--------------------------------------|
| Docker        | Run Redis + PostgreSQL in containers |
| Postman       | Test API endpoints manually          |

### Verify installations

```bash
python --version        # Python 3.11.x or higher
psql --version          # psql (PostgreSQL) 15.x
redis-cli --version     # Redis cli 7.x




































































# campusalert/README.md

# CampusAlert — Django Backend Setup Guide

A Django 6.x + Flutter alert system for Covenant University with XGBoost urgency
classification, FCM push notifications, and native ASGI WebSocket LAN delivery.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| PostgreSQL | 15+ |
| Redis | 7+ |
| Node.js | Not required — backend only |

---

## Phase 1 — Project Setup

### 1. Clone and create virtual environment

```bash
git clone <your-repo-url> campusalert
cd campusalert
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your actual values:
#   SECRET_KEY, DATABASE_URL, REDIS_URL, FCM_PROJECT_ID, etc.
nano .env
```

### 3. Create PostgreSQL database

```bash
psql -U postgres
CREATE DATABASE campusalert;
CREATE USER campusalert WITH PASSWORD 'strongpassword';
GRANT ALL PRIVILEGES ON DATABASE campusalert TO campusalert;
\q
```

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Create a superuser (first admin account)

```bash
python manage.py createsuperuser
# Then in Django shell, set role=admin and is_verified=True:
python manage.py shell
>>> from accounts.models import User
>>> u = User.objects.get(username='your_superuser_username')
>>> u.role = 'admin'; u.is_verified = True; u.save()
>>> exit()
```

### 6. Collect static files

```bash
python manage.py collectstatic --no-input
```

### 7. Start all services (development)

Open four separate terminals:

```bash
# Terminal 1 — Django ASGI server (handles HTTP + WebSocket)
uvicorn website.asgi:application --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Celery worker (handles FCM dispatch tasks)
celery -A website worker -l info -c 4

# Terminal 3 — Redis (if not running as a service)
redis-server

# Terminal 4 — (optional) Celery beat for scheduled tasks
celery -A website beat -l info
```

---

## Phase 2 — ML Model Training

### 1. Create the data directory

```bash
mkdir -p ml/data
```

### 2. Download a crisis dataset

**Option A — HumAID (recommended)**
```bash
# Download from: https://crisisnlp.qcri.org/humaid_dataset.html
# Place the CSV at: ml/data/humaid.csv
# Expected columns: tweet_text, class_label
```

**Option B — CrisisLex**
```bash
# Download from: https://crisislex.org/data-collections.html
# Place the CSV at: ml/data/crisislex26.csv
# Expected columns: tweet_text, label
```

**Option C — Synthetic only (for initial testing)**
```bash
python ml/prepare_dataset.py --source synthetic --output ml/data/synthetic_campus.csv
```

### 3. Prepare and relabel the dataset

```bash
# If using HumAID:
python ml/prepare_dataset.py --source humaid \
    --input ml/data/humaid.csv \
    --output ml/data/crisis_dataset.csv

# If using CrisisLex:
python ml/prepare_dataset.py --source crisislex \
    --input ml/data/crisislex26.csv \
    --output ml/data/crisis_dataset.csv
```

### 4. Train the XGBoost model

```bash
python ml/train.py
# Produces: ml/model.pkl, ml/vectorizer.pkl, ml/training_metadata.json
# Target: >= 80% accuracy, < 5% false alarm rate
```

### 5. Evaluate the model

```bash
python ml/evaluate.py
# Prints: per-class metrics, confusion matrix, live inference demo, keyword coverage
```

### 6. Run classifier unit tests

```bash
python manage.py test alerts.tests.test_classifier -v 2
```

---

## Phase 3 — Backend API Testing

### 1. Run all tests

```bash
python manage.py test alerts.tests -v 2
python manage.py test accounts -v 2
```

### 2. Test API endpoints with curl

#### Register a student account
```bash
curl -X POST http://localhost:8000/api/v1/accounts/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "stu001",
    "email": "stu001@covenantuniversity.edu.ng",
    "first_name": "Chidi",
    "last_name": "Okeke",
    "password": "SecurePass123!",
    "password_confirm": "SecurePass123!"
  }'
```

#### Login
```bash
curl -X POST http://localhost:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "stu001", "password": "SecurePass123!"}'
# Save the access token from the response
export TOKEN="<access_token_from_response>"
```

#### Update FCM token (Flutter calls this on launch)
```bash
curl -X PATCH http://localhost:8000/api/v1/accounts/device/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fcm_token": "fcm_device_token_from_flutter"}'
```

#### Compose an alert (admin only)
```bash
# First login as admin and get token
export ADMIN_TOKEN="<admin_access_token>"

curl -X POST http://localhost:8000/api/v1/alerts/compose/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "FIRE in Daniel Hall",
    "body": "All students must evacuate Daniel Hall immediately. Use the nearest exit.",
    "category": "security"
  }'
```

#### Get alert feed (student)
```bash
curl http://localhost:8000/api/v1/alerts/ \
  -H "Authorization: Bearer $TOKEN"
```

#### Sync missed alerts (offline recovery)
```bash
curl "http://localhost:8000/api/v1/alerts/missed/?since=2024-01-01T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

#### Acknowledge a critical alert
```bash
curl -X POST http://localhost:8000/api/v1/alerts/<alert-uuid>/acknowledge/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel": "fcm"}'
```

### 3. Test LAN WebSocket (simulated LAN demo)

Connect all test devices to the same Wi-Fi hotspot. Run the Django server on
the laptop at, say, 192.168.1.100:

```bash
uvicorn website.asgi:application --host 0.0.0.0 --port 8000
```

Test the WebSocket connection (using wscat or the Flutter app):

```bash
npm install -g wscat
wscat -c "ws://192.168.1.100:8000/ws/alerts/?token=<your_jwt_access_token>"
# You should see: {"type": "connected", "message": "CampusAlert LAN channel active."}
# When an admin sends an alert, it appears here within < 5 seconds
```

---

## Firebase Setup (FCM)

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project (or use existing): `campusalert`
3. Add an Android app with package name: `com.onehux.campusalert`
4. Download `google-services.json` → place in Flutter `android/app/`
5. Go to **Project Settings → Service Accounts**
6. Click **Generate new private key** → save JSON file
7. Add path to `.env`: `FCM_SERVICE_ACCOUNT_JSON_PATH=/path/to/service-account.json`
8. Add `FCM_PROJECT_ID=your-firebase-project-id` to `.env`

---

## Project Structure Summary

```
campusalert/
├── website/           # Django config: settings, urls, asgi (WebSocket routing), celery
├── core/              # Abstract TimeStampedModel base, custom exception handler
├── accounts/          # User model (UUID7, role, FCM token), JWT auth endpoints
├── alerts/
│   ├── models.py      # Alert (urgency, status, classification) + DeliveryLog
│   ├── services/
│   │   ├── classifier.py   # Keyword override + XGBoost inference
│   │   ├── delivery.py     # FCM + Redis pub/sub + DeliveryLog bulk creation
│   │   └── fcm.py          # Firebase HTTP v1 API
│   ├── consumers.py   # Native ASGI WebSocket consumer (LAN delivery)
│   ├── tasks.py       # Celery task: async dispatch_alert_task
│   ├── views.py       # DRF views: compose, feed, missed, acknowledge, admin
│   ├── serializers.py # Input/output serializers for all endpoints
│   ├── permissions.py # IsVerifiedUser, IsVerifiedAdminRole
│   └── tests/         # Unit tests for classifier + integration tests for views
└── ml/
    ├── train.py           # Full training pipeline: load → TF-IDF → SMOTE → XGBoost → save
    ├── evaluate.py        # Post-training evaluation: metrics + live demo + keyword coverage
    ├── prepare_dataset.py # Dataset loading, relabelling, synthetic sample generation
    └── data/              # Place CrisisLex/HumAID CSVs here
```

---

## Alert Delivery Flow

```
Admin POSTs to /api/v1/alerts/compose/
    ↓
classify_alert(title, body)          ← < 500ms
    ↓ keyword override? → return 'critical' instantly
    ↓ else → XGBoost TF-IDF inference
    ↓
Alert saved to PostgreSQL (status=CLASSIFIED)
    ↓
transaction.on_commit()
    ↓
dispatch_alert_task.delay(alert_id)  ← Celery, non-blocking
    ↓
    ├── FCM HTTP v1 → all users with internet  (< 2s)
    └── Redis pub/sub → AlertWebSocketConsumer
            ↓
        WebSocket push → all LAN-connected Flutter clients  (< 5s)

Flutter (no connectivity):
    → SQLite cache → display on reconnect
    → GET /api/v1/alerts/missed/?since=<last_seen>  ← sync endpoint
```

