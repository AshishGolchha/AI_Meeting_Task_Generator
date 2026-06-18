from google import genai
import json
import re

client = genai.Client()


def clean_json(text):
    """
    Removes ```json markdown if present
    """

    # Remove ```json ``` blocks
    text = re.sub(r"```json|```", "", text)

    return text.strip()


def extract_tasks_from_transcript(transcript):

    prompt = f"""
You are an AI Minutes of Meeting generator.

Analyze the transcript and extract:

- Summary
- Tasks
- Assigned person
- Deadline (YYYY-MM-DD if possible)
- Priority (high / medium / low)

Return ONLY valid JSON in this format:

{{
 "summary": "",
 "tasks": [
   {{
     "title": "",
     "description": "",
     "assigned_to": "",
     "deadline": "",
     "priority": ""
   }}
 ]
}}

Transcript:
{transcript}
"""

    try:

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        text = response.text

        print("\n🧠 RAW AI RESPONSE:\n", text)

        # Clean markdown if exists
        cleaned_text = clean_json(text)

        json_data = json.loads(cleaned_text)

        print("\n✅ Parsed AI JSON:\n", json_data)

        return json_data

    except Exception as e:

        print("\n❌ AI PARSE ERROR:", str(e))

        return {
            "summary": "",
            "tasks": []
        }
