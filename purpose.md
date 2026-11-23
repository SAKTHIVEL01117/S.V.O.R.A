# S.V.O.R.A — Aircraft Maintenance Intelligence Platform

> **Purpose of this document:** Complete architectural, functional, and API specification of the S.V.O.R.A backend so the `frontend/` application can be designed and implemented accurately against every endpoint, data schema, status enum, and operational constraint.

---

## 1. Application Overview & Purpose

**S.V.O.R.A** is an AI-assisted **Aircraft Maintenance Intelligence Platform** that transforms raw aircraft flight telemetry (Excel logs) into deterministic engineering analytics and manual-grounded flight-readiness / maintenance work-order reports.

### Why the Backend Uses a Two-Stage Pipeline
1. **Stage 1 — Deterministic Engineering Analytics (`POST /aircraft/analytics`)**
   - Ingests an uploaded Excel maintenance dataset (`.xlsx` / `.xls`).
   - Normalizes headers (stripping units such as `(°C)`, `(PSI)`, `(cycles)` and mapping common column aliases).
   - Extracts an aircraft's **latest flight cycle** and compares its sensor readings against the **previous 10 flight cycles** (mean, median, standard deviation, delta from average, percent change, and trend direction).
   - **Intentionally strips pre-labeled decision columns** (`Detected_Failure_Mode`, `Recommended_Maintenance_Action`, `Maintenance_Status`) from `current_record` so downstream AI analysis reasons purely from objective telemetry.
2. **Stage 2 — Manual-Grounded AI Maintenance Diagnostics (`POST /aircraft/maintenance-prediction`)**
   - Sends the structured Stage 1 analytics JSON **together with the full internal Aircraft Maintenance Manual PDF** (`AeroTech_ATX200_Maintenance_Manual.pdf`) to **Amazon Bedrock (`amazon.nova-pro-v1:0`)** via the Converse API.
   - Instructs the model to act as a Senior Aircraft Maintenance Engineer, cite only thresholds and procedures from the attached manual, avoid inventing limits, and return a strict JSON report containing:
     - Health Status & Risk Level
     - Final Fly / No-Fly Decision for the operations dashboard
     - Threshold Violations with manual citations
     - Root Cause Analysis
     - Prioritized Maintenance Actions
     - Step-by-Step Inspection Checklist
     - Generated Maintenance Work Order
     - Confidence Score & Missing Information disclosures

---

## 2. Repository & Backend Architecture

```text
S.V.O.R.A/
├── purpose.md                                         # This specification
├── frontend/                                          # Frontend application (to be built)
└── backend/
    ├── app.py                                         # FastAPI HTTP API & CORS configuration
    ├── pyproject.toml                                 # Python >=3.12 dependencies (managed with uv)
    ├── uv.lock                                        # Locked dependency graph
    ├── dockerfile                                     # Container image (Python 3.12-slim + uv + uvicorn)
    ├── .dockerignore                                  # Excludes .venv, __pycache__, .env from builds
    ├── .env                                           # Optional AWS/Bedrock environment configuration
    ├── data/
    │   ├── aircraft_maintenance_intelligence_dataset.xlsx  # Sample dataset (AIR-001 to AIR-005)
    │   └── AeroTech_ATX200_Maintenance_Manual.pdf          # Internal maintenance manual sent to Bedrock
    └── src/
        └── aircraft_maintanence/
            ├── __init__.py
            ├── engineering_analytics.py               # Stage 1: pandas/openpyxl deterministic analytics
            └── bedrock_maintenance_analyzer.py        # Stage 2: Amazon Bedrock Converse PDF + JSON analyzer
```

### Core Backend Tech Stack
- **Web Framework:** FastAPI (`1.0.0`) served via Uvicorn on port `8000`
- **Data Processing:** `pandas`, `numpy`, `openpyxl`
- **AI / Cloud:** `boto3` (`bedrock-runtime` Converse API, default model `amazon.nova-pro-v1:0`, region `us-east-1`)
- **CORS:** Enabled (`allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`) — ready for local frontend dev servers (e.g., `http://localhost:5173`, `http://localhost:3000`).
- **Interactive API Docs:** `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/openapi.json`

---

## 3. API Specification (Frontend Integration Contract)

**Default Base URL:** `http://localhost:8000`  
*(Make this configurable in the frontend via an environment variable such as `VITE_API_BASE_URL` or `NEXT_PUBLIC_API_BASE_URL`.)*

---

### 3.1 `GET /` — Service Status
Confirms the backend is reachable.

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "aircraft-maintenance-api",
  "message": "Backend is running"
}
```

---

### 3.2 `GET /testing/health` — Health Check
Lightweight endpoint for connection status indicators in the frontend header.

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "aircraft-maintenance-api"
}
```

---

### 3.3 `POST /aircraft/analytics` — Stage 1: Upload Excel & Generate Analytics

**Request:**
- **Content-Type:** `multipart/form-data`
- **Field Name:** `excel_file` (required)
- **Accepted Formats:** `.xlsx`, `.xls` (non-empty)
- **Required Columns in Sheet (aliases supported):**
  - `Aircraft_ID` (aliases: `Aircraft ID`, `Aircraft`, `Tail Number`, `Tail No`)
  - `Flight_Cycle` (aliases: `Flight_Cycle (cycles)`, `Flight Cycles`, `Cycle`, `Cycles`, `Flight Number`, `Flight No`)
- **Current Behavior:** Reads sheet index `0`, selects the first sorted aircraft ID in the file (e.g., `AIR-001`), and compares its latest flight cycle against the previous `10` flight cycles.

**Response (`200 OK`):**
```json
{
  "message": "Analytics generated successfully",
  "aircraft_id": "AIR-001",
  "summary": {
    "aircraft_id": "AIR-001",
    "latest_flight_cycle": 101,
    "current_record": {
      "Aircraft_ID": "AIR-001",
      "Aircraft_Model": "A320neo",
      "Engine_Model": "CFM LEAP-1A",
      "Airport_Code": "DEL",
      "Flight_Cycle": 101,
      "Flight_Hours": 390.0,
      "Cycles_Since_Overhaul": 101,
      "Last_Maintenance_Date": "2026-10-28",
      "Ambient_Temperature": 30.0,
      "Humidity": 150,
      "Outside_Air_Temperature": 36.0,
      "Engine_Temperature": 1500.0,
      "Exhaust_Gas_Temperature": 1000.0,
      "Oil_Temperature": 250.0,
      "Oil_Pressure": 100.0,
      "Engine_Vibration": 15.0,
      "Compressor_Pressure": 44.6,
      "Fuel_Flow": 2456.8,
      "Hydraulic_Pressure": 5000.0,
      "Engine_RPM": 9796,
      "Risk_Score": 98.0,
      "Remaining_Useful_Life": 30
    },
    "historical_window_size": 10,
    "historical_analysis": [
      {
        "column": "Engine_Vibration",
        "latest_value": 15.0,
        "historical_average": 5.756,
        "historical_median": 5.75,
        "historical_std_dev": 0.189,
        "change_from_average": 9.244,
        "change_percent": 160.598,
        "trend_direction": "INCREASING"
      }
    ]
  }
}
```

**Trend Direction Rules (`trend_direction`):**
- `"INCREASING"` — `change_percent > 3`
- `"DECREASING"` — `change_percent < -3`
- `"STABLE"` — `-3 <= change_percent <= 3`

**Error Responses:**
| HTTP Status | Cause | Example `detail` |
|---|---|---|
| `400` | Missing file, non-Excel extension, empty file, missing required columns, or no aircraft records | `"Please upload a valid Excel file (.xlsx or .xls)."` |
| `404` | Dataset file not found | `"Dataset not found: ..."` |
| `500` | Unexpected processing failure | `"Analytics failed: ..."` |

---

### 3.4 `POST /aircraft/maintenance-prediction` — Stage 2: AI Maintenance Report

**Request:**
- **Content-Type:** `application/json`
- **Accepted Payload Shapes** (any of the three work automatically):
  1. The **entire JSON response** from `POST /aircraft/analytics` (backend extracts `payload.summary`)
  2. `{ "engineering_json": { ...summary } }`
  3. The `summary` object directly

> **Frontend Timeout & Loading UX Note:** This endpoint sends the full maintenance manual PDF to Amazon Bedrock Nova Pro and typically takes **10–45 seconds**. Use a client timeout of at least **90 seconds** and display a clear multi-step loading indicator while awaiting the response.

**Response (`200 OK`):**
```json
{
  "success": true,
  "report": {
    "aircraft": "AIR-001",
    "aircraft_model": "A320neo",
    "health_status": "SAFE | MONITOR | MAINTENANCE REQUIRED | GROUND AIRCRAFT",
    "risk_level": "LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN",
    "safe_for_next_flight": true,
    "final_flight_decision": {
      "decision": "CLEARED_TO_FLY | FLY_WITH_MONITORING | MAINTENANCE_REQUIRED_BEFORE_FLIGHT | GROUND_AIRCRAFT",
      "can_fly_now": true,
      "ui_statement": "Aircraft may fly with increased monitoring.",
      "required_before_next_flight": "Increased monitoring and inspection of bearing assembly.",
      "decision_rationale": "Engine vibration exceeds warning threshold."
    },
    "overall_summary": "Executive engineering summary string...",
    "threshold_violations": [
      {
        "parameter": "Engine_Vibration",
        "observed_value": 6.08,
        "manual_threshold": "3.1 mm/s (Warning)",
        "severity": "LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN",
        "manual_reference": "Chapter 3, Table 3.1",
        "explanation": "Explanation referencing manual limits."
      }
    ],
    "root_cause": {
      "most_likely_cause": "Bearing wear or rotating assembly degradation",
      "supporting_evidence": [
        "Engine vibration trend is increasing.",
        "Engine vibration is above the warning threshold."
      ],
      "manual_reference": "Chapter 5, Section 5.1.1"
    },
    "maintenance_actions": [
      {
        "priority": 1,
        "action": "Inspect bearing assembly and rotating components",
        "reason": "Engine vibration is above the warning threshold.",
        "manual_reference": "Chapter 6, Section 6.5"
      }
    ],
    "inspection_checklist": [
      {
        "step": 1,
        "inspection_item": "Visual inspection of bearing assembly and rotating components",
        "acceptance_criteria": "No visible wear or damage.",
        "manual_reference": "Chapter 6, Section 6.5"
      }
    ],
    "work_order": {
      "title": "Increased Monitoring and Inspection",
      "aircraft_id": "AIR-001",
      "work_order_type": "INSPECTION | REPAIR | MONITORING | GROUNDING",
      "priority": "LOW | MEDIUM | HIGH | CRITICAL",
      "tasks": [
        "Perform visual inspection of bearing assembly.",
        "Review vibration sensor trend data for the preceding 10 flight cycles."
      ],
      "required_parts_or_tools": [
        "Borescope",
        "Vibration sensor data"
      ],
      "estimated_maintenance_category": "Condition-Based Maintenance"
    },
    "confidence": {
      "score": 0.8,
      "rationale": "Explanation of confidence based on telemetry and manual coverage.",
      "missing_information": [
        "List of missing parameters or manual gaps, if any."
      ]
    }
  }
}
```

**Error Responses:**
| HTTP Status | Cause | Example `detail` |
|---|---|---|
| `400` | Empty/invalid JSON body, or Bedrock returned non-JSON / invalid schema | `"Please send the analytics output from the second API."` |
| `404` | Maintenance manual PDF missing on server | `"Maintenance manual not found at: ..."` |
| `500` | AWS credentials missing/invalid or Bedrock invocation failed | `"Maintenance prediction failed: Unable to invoke Bedrock model '...'"` |

---

## 4. Telemetry Signals & Units Reference

Use this table to format labels, units, and charts in the frontend:

### Aircraft Metadata (`current_record`)
| Field | Type | Description / Unit |
|---|---|---|
| `Aircraft_ID` | `string` | Unique aircraft identifier (e.g., `AIR-001`) |
| `Aircraft_Model` | `string` | Airframe model (e.g., `A320neo`, `A321neo`) |
| `Engine_Model` | `string` | Powerplant model (e.g., `CFM LEAP-1A`, `PW1100G`) |
| `Airport_Code` | `string` | Last recorded station IATA code (e.g., `DEL`, `JFK`, `DXB`, `CDG`) |
| `Flight_Cycle` | `integer` | Latest flight cycle number (`cycles`) |
| `Flight_Hours` | `number` | Cumulative flight hours (`hrs`) |
| `Cycles_Since_Overhaul` | `integer` | Cycles since last major overhaul (`cycles`) |
| `Last_Maintenance_Date` | `string` | ISO date string (`YYYY-MM-DD`) |

### Analyzed Numeric Signals (`historical_analysis` — up to 14 items)
| Column Key | Display Label | Unit | Category |
|---|---|---|---|
| `Ambient_Temperature` | Ambient Temperature | `°C` | Environment |
| `Humidity` | Humidity | `%` | Environment |
| `Outside_Air_Temperature` | Outside Air Temperature | `°C` | Environment |
| `Engine_Temperature` | Engine Temperature | `°C` | Propulsion / Thermal |
| `Exhaust_Gas_Temperature` | Exhaust Gas Temperature (EGT) | `°C` | Propulsion / Thermal |
| `Oil_Temperature` | Oil Temperature | `°C` | Lubrication |
| `Oil_Pressure` | Oil Pressure | `PSI` | Lubrication |
| `Engine_Vibration` | Engine Vibration | `mm/s` | Mechanical / Vibration |
| `Compressor_Pressure` | Compressor Pressure | `PSI` | Propulsion / Pressure |
| `Fuel_Flow` | Fuel Flow | `kg/hr` | Fuel System |
| `Hydraulic_Pressure` | Hydraulic Pressure | `PSI` | Hydraulics |
| `Engine_RPM` | Engine RPM | `RPM` | Propulsion |
| `Risk_Score` | Risk Score | `%` | Health Metric |
| `Remaining_Useful_Life` | Remaining Useful Life (RUL) | `cycles` | Health Metric |

---

## 5. Recommended Frontend Architecture & UI Blueprint

The frontend should feel like an **aviation operations & reliability engineering dashboard** built around the two-step workflow.

### Core User Flow
1. **System Status Header:** Calls `GET /testing/health` on load to display a live backend status indicator (Online / Offline).
2. **Step 1 — Telemetry Upload Panel:**
   - Drag-and-drop file upload accepting `.xlsx` and `.xls`.
   - Submits `FormData` with field name `excel_file` to `POST /aircraft/analytics`.
   - Displays upload validation errors (`400`/`500`) clearly.
3. **Step 2 — Engineering Analytics Dashboard (rendered immediately after Stage 1):**
   - **Aircraft Identity Bar:** `Aircraft_ID`, `Aircraft_Model`, `Engine_Model`, `Airport_Code`, `Last_Maintenance_Date`, `Flight_Cycle`, `Flight_Hours`, `Cycles_Since_Overhaul`.
   - **Top KPI Cards:** `Risk_Score` (%), `Remaining_Useful_Life` (cycles), `historical_window_size` (e.g., "vs. last 10 cycles"), count of `INCREASING` / `DECREASING` / `STABLE` signals.
   - **Telemetry Trend Grid / Table & Chart:** Displays all 14 `historical_analysis` items with `latest_value`, `historical_average`, `historical_median`, `historical_std_dev`, `change_from_average`, `change_percent`, and color-coded `trend_direction` badges (`INCREASING`, `DECREASING`, `STABLE`).
   - **Primary CTA Button:** **"Run AI Maintenance Prediction"** → sends the Stage 1 JSON response to `POST /aircraft/maintenance-prediction`.
4. **Step 3 — AI Flight Decision & Maintenance Report (rendered after Stage 2):**
   - **Hero Flight Decision Banner:** Driven by `final_flight_decision` + `health_status` + `risk_level`:
     - `CLEARED_TO_FLY` / `SAFE` → Green
     - `FLY_WITH_MONITORING` / `MONITOR` → Amber / Yellow
     - `MAINTENANCE_REQUIRED_BEFORE_FLIGHT` / `MAINTENANCE REQUIRED` → Orange
     - `GROUND_AIRCRAFT` / `GROUND AIRCRAFT` → Red
     - Prominently shows `can_fly_now` badge, `ui_statement`, `required_before_next_flight`, `decision_rationale`, and `overall_summary`.
   - **Threshold Violations Section:** Cards/table showing `parameter`, `observed_value` vs `manual_threshold`, `severity` badge, `manual_reference` chip, and `explanation` (or an explicit "No threshold violations detected" state when empty).
   - **Root Cause Analysis Card:** `most_likely_cause`, bulleted `supporting_evidence`, and `manual_reference`.
   - **Prioritized Maintenance Actions:** Sorted by `priority` (ascending), displaying `action`, `reason`, and `manual_reference`.
   - **Interactive Inspection Checklist:** Sorted by `step`, with local frontend checkboxes so engineers can check off items while viewing `inspection_item`, `acceptance_criteria`, and `manual_reference`.
   - **Generated Work Order Card:** Displays `title`, `aircraft_id`, `work_order_type` badge, `priority` badge, `estimated_maintenance_category`, numbered `tasks`, and `required_parts_or_tools` chips, plus a **Print / Export JSON** button.
   - **Model Confidence & Data Gaps Panel:** Progress bar/gauge for `confidence.score` (`0.0`–`1.0` formatted as `0%`–`100%`), `rationale`, and a callout listing `missing_information` whenever non-empty.

### Status & Severity Color Mapping Reference
| Enum Field | Values & Suggested Semantics |
|---|---|
| `health_status` | `SAFE` (green), `MONITOR` (amber), `MAINTENANCE REQUIRED` (orange), `GROUND AIRCRAFT` (red) |
| `final_flight_decision.decision` | `CLEARED_TO_FLY` (green), `FLY_WITH_MONITORING` (amber), `MAINTENANCE_REQUIRED_BEFORE_FLIGHT` (orange), `GROUND_AIRCRAFT` (red) |
| `risk_level` / `severity` / `work_order.priority` | `LOW` (green), `MEDIUM` (amber), `HIGH` (orange), `CRITICAL` (red), `UNKNOWN` (gray) |
| `work_order.work_order_type` | `MONITORING` (blue), `INSPECTION` (amber), `REPAIR` (orange), `GROUNDING` (red) |
| `trend_direction` | `INCREASING` (up arrow), `DECREASING` (down arrow), `STABLE` (neutral dash) |

---

## 6. Running the Backend (Local & Docker)

### Environment Variables (`backend/.env` or Container Env)
| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-east-1` | AWS region for Amazon Bedrock Runtime |
| `BEDROCK_MODEL_ID` | `amazon.nova-pro-v1:0` | Bedrock model ID supporting PDF document input in Converse API |
| `AWS_ACCESS_KEY_ID` | *(optional — falls back to `~/.aws/credentials`)* | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | *(optional — falls back to `~/.aws/credentials`)* | AWS secret key |

### Local Development (with `uv`)
```powershell
cd backend
uv run python app.py
```
Runs at `http://localhost:8000` with auto-reload enabled.

### Docker (from `backend/`)
```powershell
docker build -f dockerfile -t maintenance-backend .
docker run --rm -p 8000:8000 -v "${env:USERPROFILE}\.aws:/root/.aws:ro" -e AWS_REGION=us-east-1 maintenance-backend
```
Or using `backend/.env`:
```powershell
docker run --rm -p 8000:8000 --env-file .env maintenance-backend
```

---

## 7. Known Backend Constraints & Future Extension Notes

1. **Single Aircraft per Upload (Current):** `POST /aircraft/analytics` currently analyzes the first aircraft (`aircraft_list[0]`) on sheet `0` with `history_window=10`. If multi-aircraft selection or custom window sizes are added later, the backend can accept optional form/query parameters (`aircraft_id`, `history_window`, `sheet_name`) and expose a `/aircraft/list` endpoint.
2. **Stateless API:** The backend does not persist uploaded datasets or past reports to a database yet. The frontend can optionally store recent reports in browser `localStorage` for quick session review.
3. **Manual Scope Disclosure:** The bundled manual (`AeroTech_ATX200_Maintenance_Manual.pdf`) is a reference manual; when an uploaded aircraft/engine model differs from the manual, Bedrock surfaces that transparently under `confidence.missing_information` — the frontend should always render `missing_information` visibly rather than hiding it.
4. **Defensive Rendering:** Because Stage 2 output comes from an LLM, the frontend should treat arrays (`threshold_violations`, `maintenance_actions`, `inspection_checklist`, `supporting_evidence`, `tasks`, `required_parts_or_tools`, `missing_information`) defensively with empty-array fallbacks (`?? []`).
