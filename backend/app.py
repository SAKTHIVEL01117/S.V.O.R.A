"""
Simple FastAPI backend for the aircraft maintenance platform.

This file exposes core endpoints:
1. Health check & system status
2. Aircraft analytics from an uploaded Excel file
3. Maintenance prediction from analytics output (Amazon Bedrock Nova Pro with manual grounding)
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure backend root directory is in sys.path for reliable module resolution
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")
load_dotenv()

import boto3
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.aircraft_maintenance.bedrock_maintenance_analyzer import (
    AircraftMaintenanceAnalyzer,
    generate_rule_based_report,
)
from src.aircraft_maintenance.engineering_analytics import AircraftEngineeringAnalytics

logger = logging.getLogger("aircraft_maintenance_api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="S.V.O.R.A Aircraft Maintenance API",
    version="1.0.0",
    description="Operational API for aircraft engineering analytics and manual-grounded maintenance reporting",
)

# Robust CORS configuration
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=False if "*" in cors_origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint for status verification and frontend health check."""
    return {
        "status": "ok",
        "service": "aircraft-maintenance-api",
        "message": "S.V.O.R.A Backend is running",
    }


@app.get("/testing/health")
def health_check() -> dict[str, str]:
    """Health check endpoint for smoke testing and container orchestrators."""
    return {"status": "ok", "service": "aircraft-maintenance-api"}


@app.get("/aircraft/sample")
def sample_dataset_info() -> dict[str, Any]:
    """Return info about the bundled sample dataset if present."""
    sample_path = BASE_DIR / "data" / "aircraft_maintenance_intelligence_dataset.xlsx"
    if not sample_path.exists():
        return {"available": False}

    analytics = AircraftEngineeringAnalytics(sample_path, sheet_name=0)
    analytics.load_dataset()
    return {
        "available": True,
        "filename": sample_path.name,
        "aircraft_ids": analytics.list_aircraft(),
    }


@app.post("/aircraft/analytics")
async def aircraft_analytics(
    excel_file: UploadFile = File(...),
    aircraft_id: str | None = Form(None),
) -> dict[str, Any]:
    """
    Generate engineering analytics from an uploaded Excel file.

    Parameters:
    - excel_file: The uploaded telemetry Excel file (.xlsx or .xls)
    - aircraft_id: (Optional) Specific aircraft ID to inspect. Defaults to first in file.
    """
    if not excel_file.filename:
        raise HTTPException(status_code=400, detail="Please upload an Excel file.")

    if not excel_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Please upload a valid Excel file (.xlsx or .xls).",
        )

    temp_path: str | None = None

    try:
        suffix = Path(excel_file.filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            content = await excel_file.read()
            temp_file.write(content)
            temp_path = temp_file.name

        analytics = AircraftEngineeringAnalytics(
            excel_path=temp_path,
            sheet_name=0,
        )
        analytics.load_dataset()

        aircraft_list = analytics.list_aircraft()
        if not aircraft_list:
            raise ValueError("No aircraft data found in the uploaded file.")

        selected_aircraft = aircraft_id if (aircraft_id and aircraft_id in aircraft_list) else aircraft_list[0]
        summary = analytics.generate_summary(
            aircraft_id=selected_aircraft,
            history_window=10,
        )
        return {
            "message": "Analytics generated successfully",
            "aircraft_id": selected_aircraft,
            "available_aircraft": aircraft_list,
            "summary": summary.to_dict(),
        }

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Analytics generation failed")
        raise HTTPException(status_code=500, detail=f"Analytics failed: {exc}") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.post("/aircraft/maintenance-prediction")
def maintenance_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a maintenance prediction report from the analytics output.

    The request body can be the full response from the analytics endpoint,
    or the nested 'summary' object directly.
    """
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Please send the analytics output payload.")

    if isinstance(payload.get("summary"), dict):
        engineering_json = payload["summary"]
    elif isinstance(payload.get("engineering_json"), dict):
        engineering_json = payload["engineering_json"]
    else:
        engineering_json = payload

    if not isinstance(engineering_json, dict) or not engineering_json:
        raise HTTPException(status_code=400, detail="The analytics payload is empty or invalid.")

    manual_pdf_path = BASE_DIR / "data" / "AeroTech_ATX200_Maintenance_Manual.pdf"

    if not manual_pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Maintenance manual not found at: {manual_pdf_path}.",
        )

    # Check execution mode: Mock/rule-based vs Amazon Bedrock
    use_mock = os.getenv("MOCK_BEDROCK", "false").lower() in ("true", "1", "yes")

    aws_region = os.getenv("AWS_REGION", "us-east-1")
    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_session_token = os.getenv("AWS_SESSION_TOKEN")
    bedrock_model_id = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")

    has_env_credentials = bool(
        aws_access_key
        and aws_access_key not in ("YOUR_ACCESS_KEY", "your_access_key_id", "")
        and aws_secret_key
        and aws_secret_key not in ("YOUR_SECRET_KEY", "your_secret_access_key", "")
    )

    # If mock is explicitly requested, run deterministic manual-grounded report
    if use_mock:
        logger.info("MOCK_BEDROCK enabled: using manual-grounded deterministic engine")
        report = generate_rule_based_report(engineering_json)
        return {"success": True, "report": report, "mode": "rule_based_mock"}

    try:
        boto3_kwargs: dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": aws_region,
        }

        if has_env_credentials:
            boto3_kwargs["aws_access_key_id"] = aws_access_key
            boto3_kwargs["aws_secret_access_key"] = aws_secret_key
            if aws_session_token:
                boto3_kwargs["aws_session_token"] = aws_session_token

        bedrock_client = boto3.client(**boto3_kwargs)

        analyzer = AircraftMaintenanceAnalyzer(
            bedrock_client=bedrock_client,
            model_id=bedrock_model_id,
            manual_pdf_path=manual_pdf_path,
            temperature=0.2,
            max_tokens=2_000,
        )

        report = analyzer.analyze(engineering_json)
        return {"success": True, "report": report, "mode": "bedrock"}

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Bedrock invocation failed: %s", exc)
        # Fallback to rule engine if configured or credentials missing
        allow_fallback = os.getenv("ALLOW_FALLBACK", "true").lower() in ("true", "1", "yes")
        if allow_fallback:
            logger.info("Falling back to manual-grounded rule engine")
            report = generate_rule_based_report(engineering_json)
            return {
                "success": True,
                "report": report,
                "mode": "manual_grounded_fallback",
                "notice": f"Generated via ATX-200 manual rules (Bedrock fallback: {exc})",
            }

        raise HTTPException(
            status_code=500,
            detail=f"Maintenance prediction failed: {exc}",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info("Starting server on %s:%d", host, port)
    uvicorn.run("app:app", host=host, port=port, reload=True)
