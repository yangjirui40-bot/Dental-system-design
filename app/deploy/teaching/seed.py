"""Initialize only the isolated classroom database with synthetic fixtures."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'adc.settings')
from bootstrap import initialize, seed
from core.db import one, rows, execute
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction

if os.environ.get('POSTGRES_HOST') != 'adc-teaching-db' or one('SELECT current_database() AS n')['n'] != 'adc_teaching':
    raise RuntimeError('Classroom database required')
bundle = Path(__file__).parent
initialize()
os.environ['DEMO_PASSWORD'] = secrets.token_urlsafe(30)
seed(demo=True)
for filename in ['demo_scenarios.py', 'demo_showcase.py', 'demo_network.py', 'demo_clinic_operations.py']:
    args = ['--teaching-only'] if filename == 'demo_scenarios.py' else ['--teaching-only', '--commit']
    subprocess.run([sys.executable, str(bundle / filename), *args], check=True, env={**os.environ, 'PYTHONPATH':'/app'})
names = ['patient','representative','reception','dentist','manager','business','finance','director']
password = json.loads((bundle / 'teaching.json').read_text())['password']
with transaction.atomic():
    accounts = rows('SELECT id, password_hash FROM user_account WHERE login_name = ANY(%s) FOR UPDATE', [names])
    if len(accounts) != len(names):
        raise RuntimeError('Classroom role set incomplete')
    for account in accounts:
        if not check_password(password, account['password_hash']):
            execute('UPDATE user_account SET password_hash=%s WHERE id=%s',[make_password(password), account['id']])
print('Classroom ready:',len(accounts),'logins')
