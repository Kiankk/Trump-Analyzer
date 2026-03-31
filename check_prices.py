import urllib.request, json

data = json.loads(urllib.request.urlopen('http://localhost:8000/api/prices').read())
print(f"LIVE: {data['live_count']}/{data['total_instruments']} instruments")
print()
for k, v in data['instruments'].items():
    price = v['price']
    if price:
        status = "LIVE" if v['healthy'] else "OFFLINE"
        print(f"  {k:5s}  ${price:>12,.2f}   [{v['source']:>7s}]  {status}")
    else:
        print(f"  {k:5s}  {'N/A':>13s}   [{v['source']:>7s}]  OFFLINE")
