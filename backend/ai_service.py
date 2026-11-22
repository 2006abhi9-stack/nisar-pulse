import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger("nisar_pulse.ai_service")


class TacticalBriefingSchema(BaseModel):
    risk_level: str = Field(
        ..., description="Standardized severity: CRITICAL, ELEVATED, MODERATE, or NOMINAL"
    )
    summary_text: str = Field(
        ..., description="Crisp, executive tactical field assessment based strictly on telemetry"
    )
    primary_driver: str = Field(
        ..., description="Inferred geophysical or structural mechanism (e.g. Surface Water Inundation, Landslide Scar, Infrastructure Damage)"
    )
    recommended_actions: list[str] = Field(
        ..., description="3 to 5 prioritized, actionable operational steps for response teams"
    )


async def generate_ai_briefing(
    analysis_record: dict[str, Any],
    operational_focus: str | None = None,
) -> dict[str, Any]:
    """Generates structured tactical mission briefing using Gemini models with strict schema."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    # Telemetry formatted into XML block
    telemetry_xml = f"""<telemetry>
  <analysis_id>{analysis_record.get('id', 'N/A')}</analysis_id>
  <source_type>{analysis_record.get('source_type', 'UNKNOWN')}</source_type>
  <impacted_area_km2>{analysis_record.get('impacted_km2', 0.0)}</impacted_area_km2>
  <mean_db_drop>{analysis_record.get('mean_db_drop', 0.0)} dB</mean_db_drop>
  <threshold_db>{analysis_record.get('threshold_db', -3.0)} dB</threshold_db>
  <severity_tier>{analysis_record.get('severity_tier', 'NOMINAL')}</severity_tier>
  <operational_focus>{operational_focus or 'General Disaster & Environmental Response'}</operational_focus>
</telemetry>"""

    system_instruction = (
        "You are NISAR-Pulse AI, a Principal Geospatial Intelligence Officer advising field teams. "
        "Analyze the provided SAR backscatter change telemetry inside <telemetry> tags. "
        "Ground your summary and recommendations strictly on the observed decibel drop and square kilometers. "
        "Do NOT invent fictional casualties, fake weather names, or hallucinated dates. "
        "Return structured JSON adhering exactly to the requested schema."
    )

    if not api_key:
        # Factual fallback without hallucination when key is absent
        tier = analysis_record.get("severity_tier", "NOMINAL")
        area = analysis_record.get("impacted_km2", 0.0)
        mean_drop = analysis_record.get("mean_db_drop", 0.0)
        return {
            "model_name": "system-deterministic-fallback",
            "risk_level": tier,
            "summary_text": (
                f"SAR change detection detected {area} km² with an average backscatter drop of {mean_drop} dB. "
                "Configure GEMINI_API_KEY in /backend/.env for deep LLM tactical synthesis."
            ),
            "primary_driver": "Significant Microwave Backscatter Loss",
            "recommended_actions": [
                "Verify ground observations at coordinate centroid.",
                "Review high-resolution optical imagery when cloud cover clears.",
                "Configure GEMINI_API_KEY to unlock automated tactical multi-agency synthesis.",
            ],
        }

    try:
        # Initialize client with 10-second minimum allowed network timeout
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10000),
        )
        preferred_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        prompt = f"Please review this SAR change detection run and provide an operational mission briefing:\n{telemetry_xml}"

        response = await client.aio.models.generate_content(
            model=preferred_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=TacticalBriefingSchema,
                temperature=0.2,
            ),
        )
        parsed = json.loads(response.text)
        return {
            "model_name": preferred_model,
            "risk_level": parsed.get("risk_level", analysis_record.get("severity_tier", "NOMINAL")),
            "summary_text": parsed.get("summary_text", "Operational analysis completed."),
            "primary_driver": parsed.get("primary_driver", "Radar Backscatter Anomaly"),
            "recommended_actions": parsed.get("recommended_actions", []),
        }
    except Exception as e:
        logger.warning(f"Gemini API call failed, falling back to deterministic synthesis: {e}")
        tier = analysis_record.get("severity_tier", "NOMINAL")
        area = analysis_record.get("impacted_km2", 0.0)
        mean_drop = analysis_record.get("mean_db_drop", 0.0)
        driver = "Surface Water / Moisture Inundation" if mean_drop <= -4.0 else "Vegetation / Structural Disturbance"
        return {
            "model_name": "system-deterministic-fallback",
            "risk_level": tier,
            "summary_text": (
                f"SAR backscatter analysis reveals {area} km² impacted with an average delta of {mean_drop} dB. "
                f"Radiometric response indicates {driver} across the observed perimeter."
            ),
            "primary_driver": driver,
            "recommended_actions": [
                f"Deploy field inspection teams to highest attenuation centroid ({mean_drop} dB).",
                f"Monitor drainage and secondary structural failure over the {area} km² impact zone.",
                "Cross-reference subsequent satellite passes for ground deformation or recovery.",
            ],
        }
