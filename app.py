import os
import time
import requests
from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from bs4 import BeautifulSoup
from openai import OpenAI
import pandas as pd
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv('OPENAI_API_KEY')

client = MongoClient(os.getenv('MONGODB_URL'))
db = client[os.getenv('DB_NAME')]

app = Flask(__name__)

client = OpenAI()

class WeatherForecastResponse(BaseModel):
    is_weather_forecast: bool
    area_affected: list[str] | None
    duration: list[str] | None

def fetch_blog_content(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator='\n')
        return text.strip()
    except Exception as e:
        raise Exception(f"Error fetching blog content: {str(e)}")

def parse_date(date_str):
    """Parse date string in MM/DD/YYYY format to datetime object."""
    try:
        return datetime.strptime(date_str, '%m/%d/%Y')
    except ValueError as e:
        logger.error(f"Failed to parse date {date_str}: {e}")
        raise

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
        "2) area_affected (array of affected state's 2-letter US state codes or null)\n"
        "3) duration (array of start and end dates in MM/DD/YYYY format or null)\n\n"
        "Your response must be valid JSON matching exactly this schema:\n\n"
        "{\n"
        '  "is_weather_forecast": boolean,\n'
        '  "area_affected": array or null,\n'
        '  "duration": array or null\n'
        "}\n\n"
        "No additional keys or text are allowed."
    )

    # Attempt to parse the response using the specified Pydantic model
    try:
        # The example usage from your snippet:
        response = client.responses.parse(
            model="gpt-4o", # gpt-4o | gpt-4o-mini
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
            return jsonify({"error": "Invalid blog URL", "status": 400}), 400
            # return jsonify({"error": f"Failed to analyze blog content."}), 400

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
    """
    POST JSON body example:
    {
        "area_affected": [
            "CA"
        ],
        "duration": [
            "05/01/2025",
            "05/10/2025"
        ],
        "is_weather_forecast": true
    }
    """
    data = request.get_json(force=True)
    affected_areas = data.get('area_affected', [])
    duration = data.get('duration', [])

    if not affected_areas:
        logger.info("No affected areas specified. No shipments affected.")
        return jsonify([]), 400

    if len(duration) != 2:
        logger.error("Duration must contain start and end dates.")
        raise ValueError("Invalid duration format")    

    start_date = parse_date(duration[0])
    end_date = parse_date(duration[1])

    collection = db['shipments']

    query = {
        '$or': [
            {'DEST_COUNTRY_CD': {'$in': affected_areas}},
            {'DESTINATION_CUST_LOCATION_CD': {'$in': affected_areas}}
        ],
        'ACT_DLVY_DT': {
            '$gte': start_date,
            '$lte': end_date
        }
    }

    logger.info(f"Querying shipments with query: {query}")
    affected_shipments = list(collection.find(query))

    for shipment in affected_shipments:
        shipment['_id'] = str(shipment['_id'])

    logger.info(f"Found {len(affected_shipments)} affected shipments")
    return jsonify(affected_shipments), 200

@app.route("/get_impacted_bookings", methods=["post"])
def get_impacted_bookings():
    data = request.get_json(force=True)
    affected_shipments = data.get('affected_shipments', [])
    
    if not affected_shipments:
        logger.info("No affected shipments specified. No booking affected.")
        return jsonify([]), 400
    
    affected_booking_numbers = [item['BK_NBR'] for item in affected_shipments]
    collection = db['bookings']

    query = {'booking_number': {'$in': affected_booking_numbers}}
    
    logger.info(f"Querying bookings with query: {query}")
    affected_bookings = list(collection.find(query))

    for booking in affected_bookings:
        booking['_id'] = str(booking['_id'])

    logger.info(f"Found {len(affected_bookings)} affected bookings")
    return jsonify(affected_bookings), 200

@app.route("/get_customer_preferences", methods=["post"])
def get_customer_preferences():
    data = request.get_json(force=True)
    affected_shipments = data.get('affected_shipments', [])
    
    if not affected_shipments:
        logger.info("No affected shipments specified. No booking affected.")
        return jsonify([]), 400
    
    try:
        contact_info_list = []
        
        # Collections
        shipments_collection = db["shipments"]
        bookings_collection = db["bookings"]
        po_collection = db["purchase_orders"]

        shipment_ids = [item["CLP_NBR"] for item in affected_shipments]
        shipments = list(shipments_collection.find({"CLP_NBR": {"$in": shipment_ids}}))

        booking_numbers = [item["BK_NBR"] for item in shipments]
        bookings = list(bookings_collection.find({"booking_number": {"$in": booking_numbers}}))

        po_numbers = [int(item["PO_NBR"]) for item in bookings]
        pos = list(po_collection.find({"PO_NBR": {"$in": po_numbers}}))

        for shipment in affected_shipments:
            contact_info = {
                "account_code": shipment["CUST_ACCT_CD"],
                "customer_name": shipment["CLP_CUST_ACCT_CD"],
                "country": shipment["DEST_COUNTRY_CD"],
                "notify1_name": shipment["NOTIFY1_NAME"],
                "notify2_name": shipment["NOTIFY2_NAME"],

                "account_name": "",
                "shipper_name": "",
                "trdg_prtnr_name": "",

                "city": "",
                "address": "",
                "destination_country": "",
            }

            booking = next((item for item in bookings if item["booking_number"] == shipment["BK_NBR"]), None)
            if booking:
                contact_info.update({
                    "account_name": booking["ACCOUNT_NAME"],
                    "shipper_name": booking["shipper_name"],
                    "trdg_prtnr_name": booking["TRDG_PRTNR_NAME"],
                })

                po = next((item for item in pos if item["PO_NBR"] == booking["PO_NBR"]), None)
                if po:
                    contact_info.update({
                        "city": po["DESTINATION_CUST_CITY_NAME"],
                        "address": f"{po["DESTINATION_CUST_CITY_NAME"]}, {po["DESTINATION_CUST_COUNTRY_NAME"]}".strip(", "),
                        "destination_country": po["DESTINATION_CUST_COUNTRY_NAME"],
                    })

            contact_info_list.append(contact_info)

        return jsonify({"contacts": contact_info_list}), 200
    
    except Exception as e:
        logger.error(f"Error retrieving customer contact info: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/d365", methods=["post"])
def d365():
    data = request.get_json(force=True)
    print("d365:", data)
    time.sleep(3)
    return jsonify({"success": True, "data": data}), 200
 
if __name__ == "__main__":
    # Run in debug mode for local development
    app.run(host="0.0.0.0", port=5000, debug=True)
