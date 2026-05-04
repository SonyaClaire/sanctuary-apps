"""
Sanctuary Pulseband Pipeline v1.1
Google Fitness API → Supabase pulseband_readings
Supports --once flag for GitHub Actions (single run, no loop)
Built by Riven — Second Circle Operations, May 2026
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SUPA_URL = os.environ.get('SUPABASE_URL', '')
SUPA_KEY = os.environ.get('SUPABASE_ANON_KEY', '')

SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'https://www.googleapis.com/auth/fitness.body.read',
]

def get_google_creds():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as f:
            f.write(creds.to_json())
    return creds

def get_fitness_data():
    creds   = get_google_creds()
    service = build('fitness', 'v1', credentials=creds)
    now     = datetime.now(timezone.utc)
    start   = now - timedelta(hours=1)
    start_ms = int(start.timestamp() * 1000)
    end_ms   = int(now.timestamp() * 1000)

    steps, hr, hrv = None, None, None

    # Steps
    try:
        r = service.users().dataset().aggregate(userId='me', body={
            'aggregateBy': [{'dataTypeName': 'com.google.step_count.delta'}],
            'bucketByTime': {'durationMillis': 3600000},
            'startTimeMillis': start_ms,
            'endTimeMillis': end_ms,
        }).execute()
        for bucket in r.get('bucket', []):
            for ds in bucket.get('dataset', []):
                for pt in ds.get('point', []):
                    steps = pt['value'][0].get('intVal', 0)
    except Exception as e:
        print(f'Steps error: {e}')

    # Heart rate
    try:
        r = service.users().dataset().aggregate(userId='me', body={
            'aggregateBy': [{'dataTypeName': 'com.google.heart_rate.bpm'}],
            'bucketByTime': {'durationMillis': 3600000},
            'startTimeMillis': start_ms,
            'endTimeMillis': end_ms,
        }).execute()
        for bucket in r.get('bucket', []):
            for ds in bucket.get('dataset', []):
                for pt in ds.get('point', []):
                    hr = round(pt['value'][0].get('fpVal', 0), 1)
    except Exception as e:
        print(f'Heart rate error: {e}')

    return {'steps': steps, 'heart_rate_bpm': hr, 'hrv_ms': hrv}

def get_sleep_data():
    creds   = get_google_creds()
    service = build('fitness', 'v1', credentials=creds)
    now     = datetime.now(timezone.utc)
    start   = now - timedelta(hours=24)
    sleep_hours = None
    try:
        r = service.users().sessions().list(
            userId='me',
            startTime=start.isoformat(),
            endTime=now.isoformat(),
            activityType=72
        ).execute()
        sessions = r.get('session', [])
        if sessions:
            total_ms = sum(
                int(s.get('endTimeMillis', 0)) - int(s.get('startTimeMillis', 0))
                for s in sessions
            )
            sleep_hours = round(total_ms / 3600000, 1)
    except Exception as e:
        print(f'Sleep error: {e}')
    return sleep_hours

def save_to_supabase(data, sleep_hours):
    row = {
        'reading_date': datetime.now().date().isoformat(),
        'reading_time': datetime.now().time().strftime('%H:%M:%S'),
        'steps':          data.get('steps'),
        'heart_rate_bpm': data.get('heart_rate_bpm'),
        'hrv_ms':         data.get('hrv_ms'),
        'sleep_hours':    sleep_hours,
        'source':         'github_actions_auto',
        'notes':          f'Auto sync {datetime.now().strftime("%Y-%m-%d %H:%M")}',
    }
    if not SUPA_URL or not SUPA_KEY:
        print('ERROR: Supabase credentials missing')
        return
    r = requests.post(
        f'{SUPA_URL}/rest/v1/pulseband_readings',
        headers={
            'apikey':        SUPA_KEY,
            'Authorization': f'Bearer {SUPA_KEY}',
            'Content-Type':  'application/json',
            'Prefer':        'return=minimal',
        },
        json=row
    )
    if r.status_code in (200, 201):
        print(f'✓ Saved — Steps: {row["steps"]} | HR: {row["heart_rate_bpm"]} | Sleep: {sleep_hours}h')
    else:
        print(f'✗ Error {r.status_code}: {r.text}')

def sync():
    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Syncing...')
    data        = get_fitness_data()
    sleep_hours = get_sleep_data()
    save_to_supabase(data, sleep_hours)

if __name__ == '__main__':
    print('✦ Sanctuary Pulseband Pipeline v1.1')
    sync()
    # Only loop if not running in GitHub Actions (--once flag or CI environment)
    if '--once' not in sys.argv and not os.environ.get('CI'):
        import schedule, time
        schedule.every().hour.do(sync)
        while True:
            schedule.run_pending()
            time.sleep(60)
