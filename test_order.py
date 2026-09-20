import requests, json
url = 'http://localhost:3001/api/private-bill/orders'
payload = {
    "quote": {
        "currency": "NGN",
        "fiatAmount": 50000,
        "zecAmount": 50.625,
        "rate": 1000,
        "fee": 625.0,
        "expiresAt": "2026-09-20T01:22:16.184444+00:00",
        "source": "backend"
    },
    "recipient": {
        "country": "NG",
        "bank": "TestBank",
        "accountNumber": "123456",
        "accountName": "John Doe"
    }
}
resp = requests.post(url, json=payload)
print('Status:', resp.status_code)
print('Response:', resp.text)
