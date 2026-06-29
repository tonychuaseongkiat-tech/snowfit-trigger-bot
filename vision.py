import json
import re
import logging
from google import genai
from google.genai import types
from shared.config import GEMINI_API_KEY

logger = logging.getLogger("vision")

client = genai.Client(api_key=GEMINI_API_KEY)

EXTRACTION_PROMPT = """Extract bedframe order details from this invoice/order form photo. Return JSON only, no other text.

{
  "design": "model number only (e.g. 1186, 116 Plain, 1253, 1254, 772)",
  "storage": "storage type (e.g. 4 Drawer, 8inch Divan, 2 Drawers, Hydraulic, Top Board)",
  "headboard": "WITH Headboard or NO Headboard",
  "color": "color code only, not the full name (e.g. FG500-14, KS-01, TITAN FG300-04, FG300-05, LC009 WOLF, FG500-09, MP012 Dark Grey, RUE001)",
  "size": "King or Queen or Single or Super",
  "thickness_cm": 22,
  "remark": ""
}

Rules:
- For headboard: if the text lists *HEADBOARD or HEADBOARD as a component, it means WITH Headboard
- For thickness_cm: extract the number from text like "22cm" or "30cm" or "37cm" or "20cm"
- For color: extract just the code part (e.g. from "Colour - Titan (FG500-14)" extract "FG500-14", from "Colour - (Infab KISA KS-01 Baby White)" extract "KS-01")
- For storage: normalize to short form (e.g. "4 Drawer Both Side" → "4 Drawer", "8inch Divan x 2" → "8inch Divan", "Hydraulic Storage" → "Hydraulic")
- For design: extract model number only (e.g. from "Model 1186" → "1186", from "Model: 116 Plain" → "116 Plain")
- For remark: include any special instructions or notes. Empty string if none
- Return ONLY the JSON object, no markdown, no explanation"""

THICKNESS_TO_MATTRESS = {
    22: "Vienna",
    30: "Spaceship",
    37: "Hokkaido",
    20: "20cm mattress",
}


def extract_order_details(photo_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """Send photo to Gemini Vision and extract order details."""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=photo_bytes, mime_type=mime_type),
                EXTRACTION_PROMPT,
            ],
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        thickness = data.get("thickness_cm")
        if isinstance(thickness, (int, float)):
            data["mattress"] = THICKNESS_TO_MATTRESS.get(int(thickness), f"{int(thickness)}cm mattress")
        else:
            data["mattress"] = ""

        logger.info("Extracted: %s", data)
        return data

    except Exception as e:
        logger.error("Gemini extraction failed: %s", e)
        return None
