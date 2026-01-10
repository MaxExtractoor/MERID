import requests
import json
import sys

def get_weather(location):
  # Use free API (e.g., OpenWeather - replace with your key)
  api_key = "your_openweather_key"
  url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=metric"
  resp = requests.get(url)
  return resp.json()

input_data = sys.stdin.read().trim()
if input_data:
  params = json.loads(input_data)
  result = get_weather(params.get('location', ''))
  print(json.dumps(result))
