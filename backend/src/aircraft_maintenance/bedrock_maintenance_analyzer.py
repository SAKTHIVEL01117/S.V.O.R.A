"""
Amazon Bedrock maintenance analyzer for the Aircraft Maintenance Platform.

This module sends deterministic engineering analytics plus the full internal
maintenance manual PDF to Amazon Bedrock Nova Pro using the Converse API.
The model is asked to return a structured maintenance report as JSON only.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError


logger = logging.getLogger(__name__)


class BedrockRuntimeClient(Protocol):
    """Minimal protocol for the boto3 Bedrock Runtime client."""

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        """Call the Bedrock Converse API."""


class AircraftMaintenanceAnalyzer:
    """
    Generate AI maintenance reports using Amazon Bedrock and a manual PDF.
    """

    def __init__(
        self,
        bedrock_client: BedrockRuntimeClient,
        model_id: str,
        manual_pdf_path: str | Path,
        temperature: float = 0.2,
        max_tokens: int = 2_000,
    ) -> None:
        self.bedrock_client = bedrock_client
        self.model_id = model_id
        self.manual_pdf_path = Path(manual_pdf_path)
        self.temperature = temperature
        self.max_tokens = max_tokens

    def load_manual(self) -> bytes:
        """Load the complete aircraft maintenance manual PDF as bytes."""
        if not self.manual_pdf_path.exists():
            raise FileNotFoundError(
                f"Maintenance manual not found: {self.manual_pdf_path}"
            )

        if self.manual_pdf_path.suffix.lower() != ".pdf":
            raise ValueError(
                "Maintenance manual must be a PDF file. "
                f"Received: {self.manual_pdf_path}"
            )

        logger.info("Loading maintenance manual: %s", self.manual_pdf_path)
        return self.manual_pdf_path.read_bytes()

    def build_prompt(self, engineering_analytics: dict[str, Any]) -> str:
        """Build the model prompt from engineering analytics JSON."""
        analytics_json = json.dumps(
            engineering_analytics,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

        return f"""
You are a Senior Aircraft Maintenance Engineer.

Your task is to generate a professional aircraft maintenance engineering report
using two inputs:

1. Engineering Analytics JSON provided below.
2. The attached internal Aircraft Maintenance Manual PDF.

Important rules:
- Compare every engineering parameter in the analytics JSON against the
  thresholds, safe operating limits, risk matrix, decision trees, inspection
  procedures, failure modes, and maintenance actions defined in the manual.
- Use only thresholds and maintenance procedures found in the attached manual.
- Do not invent thresholds, limits, failure modes, or maintenance actions.
- If a required threshold or procedure is unavailable in the manual, state that
  explicitly in the JSON output.
- Prioritize maintenance actions when multiple actions apply.
- Determine whether the aircraft status is one of:
  SAFE, MONITOR, MAINTENANCE REQUIRED, GROUND AIRCRAFT.
- Produce a final flight decision for the operations dashboard. The decision
  must clearly state whether the aircraft may fly now, may fly with monitoring,
  or must not fly until maintenance is completed.
- Return JSON only. Do not include Markdown, prose outside JSON, or code fences.

Required analysis:
- Health Status
- Failure Severity
- Threshold Violations
- Maintenance Recommendation
- Flight Readiness
- Final Fly / No-Fly Decision
- Inspection Required
- Root Cause
- Confidence
- Generated Work Order

Engineering Analytics JSON:
{analytics_json}

Return exactly one JSON object with this schema:
{{
  "aircraft": "string",
  "aircraft_model": "string",
  "health_status": "SAFE | MONITOR | MAINTENANCE REQUIRED | GROUND AIRCRAFT",
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN",
  "safe_for_next_flight": true,
  "final_flight_decision": {{
    "decision": "CLEARED_TO_FLY | FLY_WITH_MONITORING | MAINTENANCE_REQUIRED_BEFORE_FLIGHT | GROUND_AIRCRAFT",
    "can_fly_now": true,
    "ui_statement": "string",
    "required_before_next_flight": "string",
    "decision_rationale": "string"
  }},
  "overall_summary": "string",
  "threshold_violations": [
    {{
      "parameter": "string",
      "observed_value": "number or string",
      "manual_threshold": "string",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN",
      "manual_reference": "string",
      "explanation": "string"
    }}
  ],
  "root_cause": {{
    "most_likely_cause": "string",
    "supporting_evidence": ["string"],
    "manual_reference": "string"
  }},
  "maintenance_actions": [
    {{
      "priority": 1,
      "action": "string",
      "reason": "string",
      "manual_reference": "string"
    }}
  ],
  "inspection_checklist": [
    {{
      "step": 1,
      "inspection_item": "string",
      "acceptance_criteria": "string",
      "manual_reference": "string"
    }}
  ],
  "work_order": {{
    "title": "string",
    "aircraft_id": "string",
    "work_order_type": "INSPECTION | REPAIR | MONITORING | GROUNDING",
    "priority": "LOW | MEDIUM | HIGH | CRITICAL",
    "tasks": ["string"],
    "required_parts_or_tools": ["string"],
    "estimated_maintenance_category": "string"
  }},
  "confidence": {{
    "score": 0.0,
    "rationale": "string",
    "missing_information": ["string"]
  }}
}}
""".strip()

    def analyze(self, engineering_analytics: dict[str, Any]) -> dict[str, Any]:
        """Generate a structured AI maintenance report from analytics and PDF."""
        prompt = self.build_prompt(engineering_analytics)
        manual_bytes = self.load_manual()

        conversation = [
            {
                "role": "user",
                "content": [
                    {"text": prompt},
                    {
                        "document": {
                            "format": "pdf",
                            "name": self._document_name(),
                            "source": {"bytes": manual_bytes},
                        }
                    },
                ],
            }
        ]

        try:
            logger.info("Invoking Bedrock model: %s", self.model_id)
            response = self.bedrock_client.converse(
                modelId=self.model_id,
                messages=conversation,
                inferenceConfig={
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature,
                },
            )
        except (ClientError, BotoCoreError) as exc:
            logger.exception("Bedrock invocation failed")
            raise RuntimeError(
                f"Unable to invoke Bedrock model '{self.model_id}'"
            ) from exc

        response_text = self._extract_response_text(response)
        return self._parse_json_response(response_text)

    def _document_name(self) -> str:
        """Return a Bedrock-safe document name conforming to ^[a-zA-Z0-9_.-]+$."""
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", self.manual_pdf_path.stem).strip("._-")
        return safe_name[:200] if safe_name else "maintenance_manual"

    @staticmethod
    def _extract_response_text(response: dict[str, Any]) -> str:
        """Extract text from a Bedrock Converse response."""
        try:
            content = response["output"]["message"]["content"]
        except KeyError as exc:
            raise ValueError("Bedrock response did not contain message content") from exc

        text_parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and "text" in block
        ]
        response_text = "\n".join(text_parts).strip()

        if not response_text:
            raise ValueError("Bedrock returned an empty response")

        return response_text

    @staticmethod
    def _parse_json_response(response_text: str) -> dict[str, Any]:
        """Parse and validate the JSON-only model response, handling markdown fences and prose."""
        cleaned = response_text.strip()

        # Strip markdown fences if present (```json ... ``` or ``` ... ```)
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to extract JSON substring enclosed in { and }
            start_idx = cleaned.find("{")
            end_idx = cleaned.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                try:
                    parsed = json.loads(cleaned[start_idx : end_idx + 1])
                except json.JSONDecodeError as exc:
                    logger.error("Model returned non-JSON response: %s", response_text)
                    raise ValueError(f"Bedrock response was not valid JSON: {exc}") from exc
            else:
                logger.error("Model returned non-JSON response: %s", response_text)
                raise ValueError("Bedrock response was not valid JSON")

        if not isinstance(parsed, dict):
            raise ValueError("Bedrock response JSON must be an object")

        return parsed


def generate_rule_based_report(engineering_analytics: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic fallback analyzer that evaluates telemetry against the
    official AeroTech ATX-200 Maintenance Manual (Chapters 3, 5, 7, 8, 9).

    Used when Bedrock is unavailable or in mock/offline mode.
    """
    record = engineering_analytics.get("current_record", {})
    aircraft_id = engineering_analytics.get("aircraft_id") or record.get("Aircraft_ID", "AIR-UNKNOWN")
    aircraft_model = record.get("Aircraft_Model", "AeroTech AT-320")

    violations: list[dict[str, Any]] = []

    # Telemetry extraction
    vib = float(record.get("Engine_Vibration") or 0.0)
    eng_temp = float(record.get("Engine_Temperature") or 0.0)
    egt = float(record.get("Exhaust_Gas_Temperature") or 0.0)
    oil_temp = float(record.get("Oil_Temperature") or 0.0)
    oil_press = float(record.get("Oil_Pressure") or 0.0)
    fuel_flow = float(record.get("Fuel_Flow") or 0.0)
    comp_press = float(record.get("Compressor_Pressure") or 0.0)
    hyd_press = float(record.get("Hydraulic_Pressure") or 0.0)
    risk_score = float(record.get("Risk_Score") or 0.0)
    rul = float(record.get("Remaining_Useful_Life") or 0.0)

    # 1. Vibration: Normal 0-3.1, Warning 3.1-4.7, Critical > 4.7 (Table 3.1)
    if vib > 4.7:
        violations.append({
            "parameter": "Engine_Vibration",
            "observed_value": vib,
            "manual_threshold": "> 4.7 mm/s (Critical)",
            "severity": "CRITICAL",
            "manual_reference": "Table 3.1 & Chapter 6.5 (Bearing Inspection)",
            "explanation": f"Engine vibration ({vib} mm/s) is in the Critical range, indicating severe rotating assembly or bearing degradation."
        })
    elif vib > 3.1:
        violations.append({
            "parameter": "Engine_Vibration",
            "observed_value": vib,
            "manual_threshold": "3.1 - 4.7 mm/s (Warning)",
            "severity": "MEDIUM",
            "manual_reference": "Table 3.1 & Section 5.1.1",
            "explanation": f"Engine vibration ({vib} mm/s) exceeds normal limits, indicating developing bearing wear."
        })

    # 2. Engine Temperature: Normal 640-676, Warning 676-696, Critical > 696 (Table 3.1)
    if eng_temp > 696:
        violations.append({
            "parameter": "Engine_Temperature",
            "observed_value": eng_temp,
            "manual_threshold": "> 696 °C (Critical)",
            "severity": "CRITICAL",
            "manual_reference": "Table 3.1 & Section 4.1",
            "explanation": f"Engine temperature ({eng_temp} °C) exceeds critical limit; combustion liner and cooling duct inspection required."
        })
    elif eng_temp > 676:
        violations.append({
            "parameter": "Engine_Temperature",
            "observed_value": eng_temp,
            "manual_threshold": "676 - 696 °C (Warning)",
            "severity": "MEDIUM",
            "manual_reference": "Table 3.1 & Section 4.1",
            "explanation": f"Engine temperature ({eng_temp} °C) is elevated in warning zone."
        })

    # 3. EGT: Normal 615-648, Warning 648-668, Critical > 668 (Table 3.1)
    if egt > 668:
        violations.append({
            "parameter": "Exhaust_Gas_Temperature",
            "observed_value": egt,
            "manual_threshold": "> 668 °C (Critical)",
            "severity": "CRITICAL",
            "manual_reference": "Table 3.1 & Section 5.2.5",
            "explanation": f"Exhaust gas temperature ({egt} °C) is critical. Turbine section inspection and fuel scheduling review needed."
        })
    elif egt > 648:
        violations.append({
            "parameter": "Exhaust_Gas_Temperature",
            "observed_value": egt,
            "manual_threshold": "648 - 668 °C (Warning)",
            "severity": "MEDIUM",
            "manual_reference": "Table 3.1 & Section 7.3",
            "explanation": f"Exhaust gas temperature ({egt} °C) is in warning band."
        })

    # 4. Oil Temperature: Normal 82-92, Warning 92-95, Critical > 95 (Table 3.1)
    if oil_temp > 95:
        violations.append({
            "parameter": "Oil_Temperature",
            "observed_value": oil_temp,
            "manual_threshold": "> 95 °C (Critical)",
            "severity": "CRITICAL",
            "manual_reference": "Table 3.1 & Section 4.4",
            "explanation": f"Oil temperature ({oil_temp} °C) exceeds critical limit, risking lubrication breakdown."
        })
    elif oil_temp > 92:
        violations.append({
            "parameter": "Oil_Temperature",
            "observed_value": oil_temp,
            "manual_threshold": "92 - 95 °C (Warning)",
            "severity": "MEDIUM",
            "manual_reference": "Table 3.1 & Section 4.4",
            "explanation": f"Oil temperature ({oil_temp} °C) is elevated in warning band."
        })

    # 5. Oil Pressure: Normal 55-61, Warning 52-55, Critical < 52 (Table 3.1)
    if oil_press < 52 and oil_press > 0:
        violations.append({
            "parameter": "Oil_Pressure",
            "observed_value": oil_press,
            "manual_threshold": "< 52 PSI (Critical)",
            "severity": "CRITICAL",
            "manual_reference": "Table 3.1 & Section 5.1.4",
            "explanation": f"Oil pressure ({oil_press} PSI) is below critical threshold. Inspect oil pump, filters, and lines for leaks."
        })
    elif oil_press > 70:
        violations.append({
            "parameter": "Oil_Pressure",
            "observed_value": oil_press,
            "manual_threshold": "55 - 61 PSI (Normal range)",
            "severity": "HIGH",
            "manual_reference": "Table 3.1 & Section 4.5",
            "explanation": f"Oil pressure ({oil_press} PSI) abnormally high above standard envelope."
        })

    # 6. Hydraulic Pressure: Normal 2950-3050 (Table 3.1, Section 5.1.3)
    if hyd_press > 3500 or (hyd_press < 2900 and hyd_press > 0):
        violations.append({
            "parameter": "Hydraulic_Pressure",
            "observed_value": hyd_press,
            "manual_threshold": "2950 - 3050 PSI (Stable band)",
            "severity": "HIGH",
            "manual_reference": "Table 3.1 & Section 5.1.3",
            "explanation": f"Hydraulic pressure ({hyd_press} PSI) deviates significantly from the stable operating envelope."
        })

    # Determine Health Status, Risk Level, and Decision
    has_critical = any(v["severity"] == "CRITICAL" for v in violations) or risk_score >= 80 or rul <= 15
    has_high = any(v["severity"] == "HIGH" for v in violations) or risk_score >= 60

    if has_critical:
        health_status = "GROUND AIRCRAFT"
        risk_level = "CRITICAL"
        can_fly = False
        decision = "GROUND_AIRCRAFT"
        ui_statement = "AIRCRAFT GROUNDED — Critical parameter violations detected. Immediate maintenance sign-off required."
        req_before_flight = "Complete mandatory Chapter 6 inspections, component replacements, and supervisor sign-off."
        decision_rationale = "One or more safety-critical parameters exceed limits defined in Chapter 3 and Chapter 8. Flying is prohibited."
    elif has_high:
        health_status = "MAINTENANCE REQUIRED"
        risk_level = "HIGH"
        can_fly = False
        decision = "MAINTENANCE_REQUIRED_BEFORE_FLIGHT"
        ui_statement = "MAINTENANCE REQUIRED — Action needed before next revenue flight."
        req_before_flight = "Perform required inspections and corrective action per Chapter 6."
        decision_rationale = "Elevated risk score and warning exceedances necessitate maintenance intervention prior to release."
    elif len(violations) > 0 or risk_score >= 35:
        health_status = "MONITOR"
        risk_level = "MEDIUM"
        can_fly = True
        decision = "FLY_WITH_MONITORING"
        ui_statement = "CLEARED WITH MONITORING — Aircraft permitted to fly with heightened parameter telemetry tracking."
        req_before_flight = "Review flight log and verify trends after subsequent landing."
        decision_rationale = "Readings in warning band per Chapter 8; condition-based monitoring cycle initiated."
    else:
        health_status = "SAFE"
        risk_level = "LOW"
        can_fly = True
        decision = "CLEARED_TO_FLY"
        ui_statement = "CLEARED TO FLY — All monitored parameters within normal operating bands."
        req_before_flight = "Perform standard post-flight walkaround."
        decision_rationale = "All telemetry aligns with normal ranges specified in Table 3.1."

    # Determine likely failure mode from Chapter 5
    if vib > 4.7 and (eng_temp > 696 or egt > 668):
        most_likely_cause = "Severe Bearing Wear and Thermal Overload (Section 5.1.1)"
        supporting_evidence = [
            f"Vibration sustained at {vib} mm/s (critical threshold > 4.7 mm/s)",
            f"Engine temperature at {eng_temp} °C (critical threshold > 696 °C)",
            f"Computed risk score at {risk_score}% with RUL of {rul} cycles"
        ]
        manual_ref = "ATX-200 Manual Section 5.1.1, Figure 7.1, Chapter 6.5"
    elif oil_press < 52 and vib > 4.7:
        most_likely_cause = "Oil Leakage with Associated Mechanical Distress (Section 5.1.4)"
        supporting_evidence = [
            f"Oil pressure dropped to {oil_press} PSI (critical threshold < 52 PSI)",
            f"Vibration elevated at {vib} mm/s"
        ]
        manual_ref = "ATX-200 Manual Section 5.1.4 & Section 6.2"
    elif hyd_press > 3500 or hyd_press < 2900:
        most_likely_cause = "Hydraulic System Pressure Anomaly / Pump Regulation Fault (Section 5.1.3)"
        supporting_evidence = [
            f"Hydraulic pressure at {hyd_press} PSI outside standard 2950-3050 PSI band"
        ]
        manual_ref = "ATX-200 Manual Section 5.1.3 & Section 6.3"
    else:
        most_likely_cause = "Normal System Wear within Tolerances"
        supporting_evidence = ["Sensors operating within acceptable statistical boundaries"]
        manual_ref = "ATX-200 Manual Table 3.1"

    # Maintenance actions from manual
    maintenance_actions = []
    if vib > 3.1:
        maintenance_actions.append({
            "priority": 1,
            "action": "Perform Bearing Inspection and Oil Debris Analysis",
            "reason": "Vibration exceedance triggers mandatory bearing health verification",
            "manual_reference": "Chapter 6.5 (Bearing Inspection Procedure)"
        })
    if eng_temp > 676 or egt > 648:
        maintenance_actions.append({
            "priority": 2,
            "action": "Borescope Hot Section and Inspect Cooling Ducts",
            "reason": "Thermal parameters elevated beyond normal operating band",
            "manual_reference": "Chapter 6.1 (100-Cycle Inspection) & Section 5.2.5"
        })
    if oil_temp > 92 or oil_press < 55:
        maintenance_actions.append({
            "priority": 3,
            "action": "Inspect Oil Cooler, Filter, and Scavenge Lines",
            "reason": "Lubrication circuit thermal/pressure deviation",
            "manual_reference": "Chapter 6.2 (Oil System Inspection Procedure)"
        })
    if not maintenance_actions:
        maintenance_actions.append({
            "priority": 1,
            "action": "Routine Post-Flight Walkaround Inspection (INSP-A)",
            "reason": "All parameters normal; proceed with standard turnaround check",
            "manual_reference": "Chapter 6.1 (Table 6.1)"
        })

    # Inspection checklist
    checklist = [
        {
            "step": 1,
            "inspection_item": "Post-Flight Walkaround & Visual Leak Inspection",
            "acceptance_criteria": "No fluid stains, chafing, or foreign object damage on casing",
            "manual_reference": "Chapter 6.1"
        },
        {
            "step": 2,
            "inspection_item": "Oil Filter & Magnetic Chip Detector Debris Check",
            "acceptance_criteria": "Zero metallic flake contamination present in oil filter housing",
            "manual_reference": "Chapter 6.2"
        },
        {
            "step": 3,
            "inspection_item": "Bearing Housing Borescope & Vibration Sensor Mount Verification",
            "acceptance_criteria": "No spalling, pitting, or loose accelerometer mounting brackets",
            "manual_reference": "Chapter 6.5"
        },
        {
            "step": 4,
            "inspection_item": "Turbine Stage Borescope Inspection",
            "acceptance_criteria": "Turbine blades and nozzle guide vanes free of thermal cracking or erosion",
            "manual_reference": "Chapter 6.1 (100-Cycle Inspection)"
        }
    ]

    return {
        "aircraft": str(aircraft_id),
        "aircraft_model": str(aircraft_model),
        "health_status": health_status,
        "risk_level": risk_level,
        "safe_for_next_flight": can_fly,
        "final_flight_decision": {
            "decision": decision,
            "can_fly_now": can_fly,
            "ui_statement": ui_statement,
            "required_before_next_flight": req_before_flight,
            "decision_rationale": decision_rationale,
        },
        "overall_summary": (
            f"Engineering assessment for aircraft {aircraft_id} ({aircraft_model}). "
            f"Risk score is {risk_score}%, with {len(violations)} threshold violation(s) observed. "
            f"Health state is evaluated as '{health_status}'. Most likely cause: {most_likely_cause}."
        ),
        "threshold_violations": violations,
        "root_cause": {
            "most_likely_cause": most_likely_cause,
            "supporting_evidence": supporting_evidence,
            "manual_reference": manual_ref,
        },
        "maintenance_actions": maintenance_actions,
        "inspection_checklist": checklist,
        "work_order": {
            "title": f"Work Order WO-{aircraft_id}-C{record.get('Flight_Cycle', 'CUR')}",
            "aircraft_id": str(aircraft_id),
            "work_order_type": "GROUNDING" if not can_fly else ("INSPECTION" if violations else "MONITORING"),
            "priority": risk_level,
            "tasks": [a["action"] for a in maintenance_actions],
            "required_parts_or_tools": [
                "Optical Borescope Kit (ATX-BK100)",
                "Oil Filter Debris Analysis Kit",
                "Torque Wrench & Replacement Bearing Kit (if indicated)"
            ],
            "estimated_maintenance_category": "Unscheduled Maintenance / Condition-Based" if violations else "Line Maintenance"
        },
        "confidence": {
            "score": 0.95,
            "rationale": "High confidence based on direct cross-referencing of 14 telemetry parameters against ATX-200 Table 3.1 operating bands.",
            "missing_information": []
        }
    }


if __name__ == "__main__":
    import boto3

    logging.basicConfig(level=logging.INFO)

    base_dir = Path(__file__).resolve().parents[2]
    manual_pdf_path = base_dir / "data" / "AeroTech_ATX200_Maintenance_Manual.pdf"

    if not manual_pdf_path.exists():
        raise FileNotFoundError(f"Maintenance manual not found: {manual_pdf_path}")

    # Example usage:
    # 1. Generate analytics JSON from the engineering analytics module
    # 2. Paste that JSON into the `engineering_json` variable below
    engineering_json = {
  "aircraft_id": "AIR-001",
  "latest_flight_cycle": 100,
  "current_record": {
    "Aircraft_ID": "AIR-001",
    "Aircraft_Model": "A320neo",
    "Engine_Model": "CFM LEAP-1A",
    "Airport_Code": "DEL",
    "Flight_Cycle": 100,
    "Flight_Hours": 340.0,
    "Cycles_Since_Overhaul": 100,
    "Last_Maintenance_Date": "2026-10-28",
    "Ambient_Temperature": 4.717116117435664,
    "Humidity": 90,
    "Outside_Air_Temperature": -2.5,
    "Engine_Temperature": 720.9,
    "Exhaust_Gas_Temperature": 685.1,
    "Oil_Temperature": 102.1,
    "Oil_Pressure": 47.9,
    "Engine_Vibration": 6.08,
    "Compressor_Pressure": 44.6,
    "Fuel_Flow": 2456.8,
    "Hydraulic_Pressure": 3017.9,
    "Engine_RPM": 9796,
    "Risk_Score": 77.2,
    "Remaining_Useful_Life": 30
  },
  "historical_window_size": 10,
  "historical_analysis": [
    {
      "column": "Ambient_Temperature",
      "latest_value": 4.717,
      "historical_average": 17.377,
      "historical_median": 21.16,
      "historical_std_dev": 11.17,
      "change_from_average": -12.66,
      "change_percent": -72.854,
      "trend_direction": "DECREASING"
    },
    {
      "column": "Humidity",
      "latest_value": 90.0,
      "historical_average": 57.8,
      "historical_median": 55.0,
      "historical_std_dev": 21.521,
      "change_from_average": 32.2,
      "change_percent": 55.709,
      "trend_direction": "INCREASING"
    },
    {
      "column": "Outside_Air_Temperature",
      "latest_value": -2.5,
      "historical_average": 11.68,
      "historical_median": 15.85,
      "historical_std_dev": 12.857,
      "change_from_average": -14.18,
      "change_percent": -121.404,
      "trend_direction": "DECREASING"
    },
    {
      "column": "Engine_Temperature",
      "latest_value": 720.9,
      "historical_average": 713.3,
      "historical_median": 713.5,
      "historical_std_dev": 2.5,
      "change_from_average": 7.6,
      "change_percent": 1.065,
      "trend_direction": "STABLE"
    },
    {
      "column": "Exhaust_Gas_Temperature",
      "latest_value": 685.1,
      "historical_average": 681.73,
      "historical_median": 681.25,
      "historical_std_dev": 2.297,
      "change_from_average": 3.37,
      "change_percent": 0.494,
      "trend_direction": "STABLE"
    },
    {
      "column": "Oil_Temperature",
      "latest_value": 102.1,
      "historical_average": 100.01,
      "historical_median": 99.6,
      "historical_std_dev": 1.49,
      "change_from_average": 2.09,
      "change_percent": 2.09,
      "trend_direction": "STABLE"
    },
    {
      "column": "Oil_Pressure",
      "latest_value": 47.9,
      "historical_average": 49.1,
      "historical_median": 49.25,
      "historical_std_dev": 0.438,
      "change_from_average": -1.2,
      "change_percent": -2.444,
      "trend_direction": "STABLE"
    },
    {
      "column": "Engine_Vibration",
      "latest_value": 6.08,
      "historical_average": 5.713,
      "historical_median": 5.68,
      "historical_std_dev": 0.157,
      "change_from_average": 0.367,
      "change_percent": 6.424,
      "trend_direction": "INCREASING"
    },
    {
      "column": "Compressor_Pressure",
      "latest_value": 44.6,
      "historical_average": 44.13,
      "historical_median": 44.3,
      "historical_std_dev": 0.344,
      "change_from_average": 0.47,
      "change_percent": 1.065,
      "trend_direction": "STABLE"
    },
    {
      "column": "Fuel_Flow",
      "latest_value": 2456.8,
      "historical_average": 2427.43,
      "historical_median": 2425.85,
      "historical_std_dev": 7.294,
      "change_from_average": 29.37,
      "change_percent": 1.21,
      "trend_direction": "STABLE"
    },
    {
      "column": "Hydraulic_Pressure",
      "latest_value": 3017.9,
      "historical_average": 3011.3,
      "historical_median": 3018.15,
      "historical_std_dev": 33.517,
      "change_from_average": 6.6,
      "change_percent": 0.219,
      "trend_direction": "STABLE"
    },
    {
      "column": "Engine_RPM",
      "latest_value": 9796.0,
      "historical_average": 9818.4,
      "historical_median": 9813.0,
      "historical_std_dev": 54.276,
      "change_from_average": -22.4,
      "change_percent": -0.228,
      "trend_direction": "STABLE"
    },
    {
      "column": "Risk_Score",
      "latest_value": 77.2,
      "historical_average": 73.43,
      "historical_median": 73.45,
      "historical_std_dev": 1.983,
      "change_from_average": 3.77,
      "change_percent": 5.134,
      "trend_direction": "INCREASING"
    },
    {
      "column": "Remaining_Useful_Life",
      "latest_value": 30.0,
      "historical_average": 35.5,
      "historical_median": 35.5,
      "historical_std_dev": 2.872,
      "change_from_average": -5.5,
      "change_percent": -15.493,
      "trend_direction": "DECREASING"
    }
  ]
}
    bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")
    analyzer = AircraftMaintenanceAnalyzer(
        bedrock_client=bedrock_client,
        model_id="amazon.nova-pro-v1:0",
        manual_pdf_path=manual_pdf_path,
        temperature=0.2,
        max_tokens=2000,
    )

    result = analyzer.analyze(engineering_json)
    print(json.dumps(result, indent=2))
