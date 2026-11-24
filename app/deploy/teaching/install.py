"""Provision the classroom beside the established ADC Docker Compose project."""
from pathlib import Path
import os
import secrets
import subprocess

here = Path(__file__).resolve().parent
def inspect(container, fmt):
    return subprocess.check_output(['docker','inspect','-f',fmt,container],text=True).strip()
env = here / '.env'
if not env.exists():
    fields = {
        'TEACHING_POSTGRES_IMAGE':inspect('adc-clinic-db-1','{{.Config.Image}}'),
        'TEACHING_API_IMAGE':inspect('adc-clinic-api-1','{{.Config.Image}}'),
        'TEACHING_WEB_NETWORK':'adc-clinic_default',
        'TEACHING_DB_PASSWORD':secrets.token_urlsafe(36),
        'TEACHING_SIGNING_KEY':secrets.token_urlsafe(48)
    }
    with os.fdopen(os.open(env,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as output:
        for k,v in fields.items():
            output.write(f'{k}={v}\n')
cmd = ['docker','compose','--project-directory',str(here),'-f',str(here/'compose.yaml')]
subprocess.run(cmd+['up','-d','--no-build','--pull','never','--wait','db'],check=True)
subprocess.run(cmd+['run','--rm','--no-deps','-T','-v',str(here)+':/seed:ro','teaching-api','python','/seed/seed.py'],check=True)
subprocess.run(cmd+['up','-d','--no-build','--pull','never','--wait','teaching-api'],check=True)
