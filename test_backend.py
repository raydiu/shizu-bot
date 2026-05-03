import requests
import json

try:
    response = requests.post(
        'https://shizu-bot-backend-production.up.railway.app/create-checkout-session',
        json={'discord_id':'123456789012345678','guild_id':'123456789012345678'},
        timeout=15
    )
    print('Status:', response.status_code)
    print('Response:', response.text[:500])
except Exception as e:
    print('Error:', str(e))