import urllib.request, json
url = 'https://api.github.com/repos/Zedda-Labs/Zedda/actions/runs?per_page=5'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        run_id = 29476205143
        jobs_url = f'https://api.github.com/repos/Zedda-Labs/Zedda/actions/runs/{run_id}/jobs?per_page=100'
        
        req2 = urllib.request.Request(jobs_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req2) as resp2:
            jobs_data = json.loads(resp2.read().decode())
            for job in jobs_data['jobs']:
                if job['conclusion'] == 'failure':
                    print(f"FAILED JOB: {job['name']}")
                    if 'ubuntu-latest / 3.9' in job['name']:
                        logs_url = f"https://api.github.com/repos/Zedda-Labs/Zedda/actions/jobs/{job['id']}/logs"
                        req3 = urllib.request.Request(logs_url, headers={'User-Agent': 'Mozilla/5.0'})
                        try:
                            with urllib.request.urlopen(req3) as resp3:
                                print(resp3.read().decode())
                        except Exception as e:
                            print("Logs error:", e)
except Exception as e:
    print('Error:', e)
