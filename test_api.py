import requests
import json

# Test de l'API /estimate/
response = requests.post(
    'http://localhost:8000/api/estimate/',
    json={
        'depart': {'lat': 3.8547, 'lon': 11.5021},
        'arrivee': {'lat': 3.8667, 'lon': 11.5174}
    },
    headers={'Authorization': 'ApiKey 974e9428-6ce2-48e7-b74b-93f572007ef8'}
)

print(f"Status Code: {response.status_code}")
print(f"Response:\n{json.dumps(response.json() if response.headers.get('content-type','').startswith('application/json') else {'text': response.text[:1000]}, indent=2, ensure_ascii=False)}")
