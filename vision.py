import json
import re
import logging
from google import genai
from google.genai import types
from shared.config import GEMINI_API_KEY

logger = logging.getLogger("vision")

client = genai.Client(api_key=GEMINI_API_KEY)

EXTRACTION_PROMPT = """Extract bedframe order details from this invoice/order form photo.

If there are MULTIPLE bedframes in the photo, return a JSON ARRAY with one object per bedframe, in the order they appear.
If there is only ONE bedframe, still return a JSON ARRAY with one object.

Each object:
{
  "design": "model number only (e.g. 1186, 116 Plain, 1253, 1254, 772)",
  "storage": "storage type (e.g. 4 Drawer, 8inch Divan, 2 Drawers, Hydraulic, Storage, Top Board)",
  "headboard": "WITH Headboard or NO Headboard",
  "color": "color code only (e.g. FG500-14, KS-01, FG500-01, FG500-11, TITAN FG300-04, LC009 WOLF)",
  "size": "King or Queen or Single or Super",
  "thickness_cm": 22,
  "remark": ""
}

Rules:
- For headboard: if *HEADBOARD or HEADBOARD is listed as a component, it means WITH Headboard
- For thickness_cm: extract the number from text like "22cm" or "30cm" or "37cm" or "20cm"
- For color: extract just the code part (e.g. from "FG500-01 / Spacechip+" extract "FG500-01")
- For storage: normalize to short form (e.g. "4 Drawer Both Side" → "4 Drawer", "8inch Divan x 2" → "8inch Divan", "Storage Bedframe" → "Storage")
- For design: model number only (e.g. "Model 1253" → "1253")
- Return ONLY the JSON array, no markdown, no explanation"""

PDF_EXTRACTION_PROMPT = """Extract bedframe order details from this Snowfit Singapore proforma invoice PDF.
Focus on the ITEMS CONSIST section for bedframe details and the *Remark* section for delivery date.

Return ONLY a valid JSON object (not an array). No markdown, no explanation.

{
  "design": "model number only (e.g. 1186, 116 Plain, 1253, 1254, 772)",
  "storage": "storage type (e.g. 4 Drawer, 8inch Divan, 2 Drawers, Hydraulic, Storage, Top Board)",
  "headboard": "WITH Headboard or NO Headboard",
  "color": "color code only (e.g. FG500-14, KS-01, FG500-01, TITAN FG300-04, LC009 WOLF)",
  "size": "King or Queen or Single or Super",
  "thickness_cm": 22,
  "remark": "from Special Remark line in ITEMS CONSIST section only",
  "delivery_text": "simplified delivery info from *Remark* section",
  "sales_person": "from Person In Charge field, UPPERCASE"
}

Rules:
- For headboard: if ITEMS CONSIST contains "(Model [number])" (e.g. "(Model 1186)", "(Model 1253)"), return "WITH Headboard". If no (Model [number]) pattern found, return "NO Headboard"
- For thickness_cm: extract the number from text like "22cm" or "30cm" or "37cm" or "20cm"
- For color: extract just the code part (e.g. from "FG500-01 / Spacechip+" extract "FG500-01")
- For storage: normalize to short form (e.g. "4 Drawer Both Side" → "4 Drawer", "8inch Divan x 2" → "8inch Divan", "Storage Bedframe" → "Storage")
- For design: model number only (e.g. "Model 1253" → "1253")
- For remark: look in ITEMS CONSIST section for "Special Remark - xxx" and extract the detail after the dash. Empty string if none
- For delivery_text: from *Remark* section, find the delivery line (e.g. "Delivery end of Oct", "Delivery 5th Aug"). Return in simplified format:
  - If only a month is mentioned (e.g. "Delivery end of Oct", "Delivery mid Nov", "Delivery Oct"): return JUST the month name (e.g. "Oct", "Nov"). Strip "end of", "mid", "early", "beginning of", "late" etc.
  - If a specific date is mentioned (e.g. "Delivery 5th Aug", "Delivery 15 Jul"): return as "5Aug", "15Jul" (day + month abbreviation, no spaces, no ordinal suffix)
- For sales_person: from "Person In Charge:" field, UPPERCASE
- Return ONLY the JSON object"""


THICKNESS_TO_MATTRESS = {
    22: "Vienna",
    30: "Spaceship",
    37: "Hokkaido",
    20: "20cm mattress",
}


def extract_order_details(photo_bytes: bytes, mime_type: str = "image/jpeg") -> list[dict] | None:
    """Send photo to Gemini Vision and extract order details. Returns a list of orders."""
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

        if isinstance(data, dict):
            data = [data]

        for item in data:
            thickness = item.get("thickness_cm")
            if isinstance(thickness, (int, float)):
                item["mattress"] = THICKNESS_TO_MATTRESS.get(int(thickness), f"{int(thickness)}cm mattress")
            else:
                item["mattress"] = ""

        logger.info("Extracted %d order(s): %s", len(data), data)
        return data

    except Exception as e:
        logger.error("Gemini extraction failed: %s", e)
        return None


def extract_order_from_pdf(pdf_bytes: bytes) -> dict | None:
    """Extract bedframe order details from invoice PDF using Gemini 2.0 Flash."""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                PDF_EXTRACTION_PROMPT,
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

        logger.info("PDF extraction: %s", data)
        return data

    except Exception as e:
        logger.error("Gemini PDF extraction failed: %s", e)
        return None
