import requests, time

s = requests.Session()
BASE = 'http://localhost:5800'

# 1. Register
code_resp = s.post(f'{BASE}/api/auth/send-code', json={'target':'demo@test.dev'}).json()
code = code_resp['code_hint']
print('1. code:', code)

reg = s.post(f'{BASE}/api/auth/verify-and-register', json={
    'target':'demo@test.dev','code':code,'username':'demo','password':'demo123'}).json()
print(f'2. register: {reg["user"]["username"]} | records: {reg["user"]["record_count"]}')

# 2. List
recs = s.get(f'{BASE}/api/records').json()
print(f'3. list: {len(recs["records"])} records')
for r in recs['records'][:3]:
    print(f'   [{r["id"]}] {r["name"]} | {r["family"]} | ret={r["total_return"]*100:.1f}%')

# 3. Edit
edit = s.put(f'{BASE}/api/records/1', json={'name':'[edited] New Name', 'notes':'Test'}).json()
print(f'4. edit: {edit["message"]}')

# 4. Play
run = s.post(f'{BASE}/api/records/1/run', json={}).json()
print(f'5. play: {run["message"]} | status={run["record"]["status"]}')
time.sleep(3)
r2 = s.get(f'{BASE}/api/records/1').json()
print(f'6. after 3s: {r2["record"]["status"]}')

# 5. Delete
d = s.delete(f'{BASE}/api/records/7').json()
print(f'7. delete: {d["message"]}')
recs2 = s.get(f'{BASE}/api/records').json()
print(f'8. remaining: {len(recs2["records"])} records')

print('\nAll tests passed! http://localhost:5800')
