import os
import time
import requests
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv('OPENAI_API_KEY')

app = Flask(__name__)

client = OpenAI()

class WeatherForecastResponse(BaseModel):
    is_weather_forecast: bool
    area_affected: str | None
    duration: str | None

def fetch_blog_content(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator='\n')
        return text.strip()
    except Exception as e:
        raise Exception(f"Error fetching blog content: {str(e)}")

@app.route("/", methods=["get"])
def home():
    return "Welcome Camunda Advisory", 200

@app.route("/check_blog", methods=["POST"])
def check_blog():
    """
    POST JSON body example:
    {
        "blog_url": "https://weatherwest.com/"
    }
    """
    data = request.get_json(force=True)
    print("request blog_url", data)
    blog_url = data.get("blog_url")
    if not blog_url:
        return jsonify({"error": "Please provide a 'blog_url'"}), 400
    
    # Fetch blog content
    try:
        # blog_response = requests.get(blog_url, timeout=10)
        # blog_response.raise_for_status()
        # blog_content = blog_response.text
        blog_content = fetch_blog_content(blog_url)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch or read blog content: {str(e)}"}), 400

    # System prompt to strictly enforce a JSON structure that matches our Pydantic model
    system_prompt = (
        "You are a helpful assistant that extracts the following weather-forecast information "
        "from a blog article:\n\n"
        "1) is_weather_forecast (boolean)\n"
        "2) area_affected (string or null)\n"
        "3) duration (string or null)\n\n"
        "Your response must be valid JSON matching exactly this schema:\n\n"
        "{\n"
        '  "is_weather_forecast": boolean,\n'
        '  "area_affected": string or null,\n'
        '  "duration": string or null\n'
        "}\n\n"
        "No additional keys or text are allowed."
    )

    # Attempt to parse the response using the specified Pydantic model
    try:
        # The example usage from your snippet:
        response = client.responses.parse(
            model="gpt-4.1-nano", # gpt-4o | gpt-4o-mini
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": blog_content},
            ],
            text_format=WeatherForecastResponse,
        )
        parsed_output = response.output_parsed  # This should be a WeatherForecastResponse object

        if (parsed_output.is_weather_forecast is not None):
            return jsonify({
                "is_weather_forecast": parsed_output.is_weather_forecast,
                "area_affected": parsed_output.area_affected,
                "duration": parsed_output.duration
            }), 200
        else:
            return jsonify({"error": f"Failed to analyze blog content."}), 400

    except ValidationError as ve:
        # If the AI's JSON doesn't match our WeatherForecastResponse model, return error + raw response
        return jsonify({
            "error": "Invalid AI response structure",
            "validation_error": str(ve),
            # If response made it this far, we can show the raw text. 
            # Some libraries store it as response.output_text or similarly.
            "raw_ai_response": getattr(response, "output_text", "No raw text available")
        }), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/get_impacted_routes", methods=["post"])
def get_impacted_routes():
    print("get_impacted_routes")
    time.sleep(3)
    return jsonify([]), 200

@app.route("/get_impacted_bookings", methods=["post"])
def get_impacted_bookings():
    print("get_impacted_bookings")
    time.sleep(3)
    return jsonify([]), 200

@app.route("/get_customer_preferences", methods=["post"])
def get_customer_preferences():
    print("get_customer_preferences")
    time.sleep(3)
    return jsonify([]), 200

@app.route("/d365", methods=["post"])
def d365():
    print("d365")
    time.sleep(3)
    return jsonify({"success": True}), 200

if __name__ == "__main__":
    # Run in debug mode for local development
    app.run(host="0.0.0.0", port=5000, debug=True)
