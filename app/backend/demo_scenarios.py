"""Explicit synthetic teaching fixtures through real use-case endpoints.

Never called by server startup. Requires --teaching-only and the existing
synthetic patient. Preserves business history. Historical visit uses an explicit
simulated teaching clock; it is not a production encounter or clinical advice.
"""
import os,sys,json,uuid
os.environ.setdefault('DJANGO_SETTINGS_MODULE','adc.settings')
import django
django.setup()
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
from django.test import Client
from django.db import transaction
from django.utils import timezone
from core.db import one,rows,get
from core.security import token,scopes

assert '--teaching-only' in sys.argv,'Only explicit synthetic teaching installations are supported'
patient=one("SELECT * FROM patient WHERE account_no='P-DEMO-001' AND email='patient@example.invalid'")
assert patient,'This script must not run on a real patient database'
tz=ZoneInfo('Asia/Shanghai');today=timezone.localdate();now=timezone.now();client=Client(SERVER_NAME='localhost')
accounts={k:one('SELECT * FROM user_account WHERE login_name=%s',[k]) for k in ['business','director','dentist','patient','reception']}
def call(role,code,body):
    account=accounts[role];scope=scopes(account['id'])[0]
    response=client.post('/api/use-cases/'+code,data=json.dumps(body,default=str),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+token(account,scope['id']),HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
    result=response.json()
    if response.status_code!=200:raise RuntimeError(f'{code}/{body.get("action")}: {response.status_code}: {result.get("message")}')
    return result
with transaction.atomic():
    # Fixture version lives in its teaching plan revision; no schema or fake catalog entry.
    marker=one("SELECT id FROM plan_revision WHERE change_reason='DEMO26-COMPLETE'")
    if marker:
        print('Enhanced synthetic scenarios already present; no history overwritten');sys.exit(0)
    clinics=rows('SELECT * FROM clinic ORDER BY id LIMIT 2');dentist=accounts['dentist']['employee_id'];kind=one('SELECT * FROM qualification_kind ORDER BY id LIMIT 1')
    doctors=[dentist]
    for i,name in enumerate(['许知微','陈奕安'],1):
        e=call('business','UC08',{'action':'employee','full_name':name,'birth_date':'1990-06-15','home_address':'教学模拟地址（非真实资料）','phone':f'1380000310{i}','email':f'demo-doctor-{i}@example.invalid','employed_from':'2020-01-01'})
        call('business','UC08',{'action':'dentist','employee_id':e['id'],'professional_no':f'DEMO-26-DOCTOR-{i}'})
        call('business','UC08',{'action':'qualification','dentist_id':e['id'],'qualification_kind_id':kind['id'],'certificate_no':f'DEMO-26-QUAL-{i}','issuing_organisation':'课程模拟发证机构','valid_from':'2020-01-01','verification_result':'verified'})
        doctors.append(e['id'])
    for i,(name,unit,price,minutes) in enumerate([('X光检查','张',60,20),('牙面抛光','次',80,20),('植牙','颗',3600,90),('牙桥修复','单位',1600,60),('牙冠修复','颗',1800,60)],1):
        catalog=call('business','UC10',{'action':'catalog','treatment_code':f'DEMO26-T{i:02}','treatment_name':name})
        standard=call('business','UC10',{'action':'draft','treatment_id':catalog['id'],'treatment_name':name,'unit_name':unit,'quantity_scale':0,'unit_price':price,'duration_minutes':minutes,'site_requirement':'由牙医核实实际部位','valid_from':(now-timedelta(days=30)).isoformat(),'qualification_kind_ids':[kind['id']]})
        call('director','UC10',{'action':'approve','id':standard['id'],'retire_previous':False})
    # A second clinic and more than one actual qualified doctor can be selected.
    for days in range(1,15):
        day=today+timedelta(days=days)
        for index,clinic in enumerate(clinics):
            cal=one('SELECT * FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s AND session_no=1',[clinic['id'],day])
            if not cal:cal=call('business','UC15',{'action':'calendar','clinic_id':clinic['id'],'work_date':day.isoformat(),'session_no':1,'is_open':True,'starts_at':datetime.combine(day,time(9),tz).isoformat(),'ends_at':datetime.combine(day,time(18),tz).isoformat()})
            doc=doctors[index+1]
            call('business','UC09',{'action':'publish','clinic_id':clinic['id'],'dentist_id':doc,'calendar_id':cal['id'],'starts_at':datetime.combine(day,time(9),tz).isoformat(),'ends_at':datetime.combine(day,time(18),tz).isoformat(),'qualification_kind_ids':[kind['id']]})
    # Historical synthetic consultation follows book -> arrive -> start -> sign.
    day=today-timedelta(days=2);start=datetime.combine(day,time(10),tz);clinic=clinics[0]
    with patch('django.utils.timezone.now',return_value=start-timedelta(days=1)):
        cal=call('business','UC15',{'action':'calendar','clinic_id':clinic['id'],'work_date':day.isoformat(),'session_no':9,'is_open':True,'starts_at':datetime.combine(day,time(9),tz).isoformat(),'ends_at':datetime.combine(day,time(18),tz).isoformat()})
        duty=call('business','UC09',{'action':'publish','clinic_id':clinic['id'],'dentist_id':dentist,'calendar_id':cal['id'],'starts_at':datetime.combine(day,time(9),tz).isoformat(),'ends_at':datetime.combine(day,time(18),tz).isoformat(),'qualification_kind_ids':[kind['id']]})
    op=one("SELECT * FROM operatory WHERE clinic_id=%s AND resource_state='active' ORDER BY id LIMIT 1",[clinic['id']]);exam=one("SELECT * FROM treatment_standard WHERE treatment_name='初步检查' AND approval_state='approved' ORDER BY id LIMIT 1")
    with patch('django.utils.timezone.now',return_value=start-timedelta(hours=1)),patch('django.utils.timezone.localdate',return_value=day):
        a=call('patient','UC02',{'action':'book','patient_id':patient['id'],'clinic_id':clinic['id'],'dentist_id':dentist,'duty_id':duty['id'],'operatory_id':op['id'],'starts_at':start.isoformat(),'ends_at':(start+timedelta(minutes=20)).isoformat(),'standard_ids':[exam['id']],'presenting_request':'教学模拟：检查与分阶段治疗评估'})
    with patch('django.utils.timezone.now',return_value=start),patch('django.utils.timezone.localdate',return_value=day):
        call('patient','UC04',{'action':'arrive','appointment_id':a['id']})
        en=call('dentist','UC04',{'action':'start','appointment_id':a['id'],'identity_confirmed':True,'allergy_confirmed':True})
        call('dentist','UC05',{'action':'sign','encounter_id':en['id'],'chief_complaint':'教学模拟：进食不适，要求检查。','present_illness':'教学模拟：近期出现，具体情况已面谈核实。','medical_history':'教学模拟：已逐项询问既往史。','examination_summary':'教学模拟：完成基础口腔检查。','tests_summary':'教学模拟：本次未实施辅助检查。','diagnosis_summary':'教学模拟：后续需分阶段评估。','management_summary':'教学模拟：本次仅实际实施初步检查。','aftercare':'教学模拟：按确认阶段接续，出现异常及时联系门店。','allergy_review':'教学模拟：已再次询问，尚无已核实逐项过敏。','consent_scope':'同意本次基础检查（教学模拟）','evidence_reference':'课堂合成场景，不存在真实患者同意材料','treatments':[{'standard_id':exam['id'],'actual_quantity':1,'charged_unit_price':exam['unit_price'],'implementation_result':'performed','site_description':'教学模拟：全口检查'}]})
    clean=one("SELECT * FROM treatment_standard WHERE treatment_name='超声洁治' AND approval_state='approved' ORDER BY id LIMIT 1")
    repair=one("SELECT * FROM treatment_standard WHERE treatment_name='树脂充填' AND approval_state='approved' ORDER BY id LIMIT 1")
    plan=call('dentist','UC13',{'action':'confirm','change_reason':'DEMO26-COMPLETE','encounter_id':en['id'],'consent_scope':'已说明阶段顺序、分支和承接门店（教学模拟）','evidence_reference':'课堂合成场景，无真实临床效力','phases':[
        {'phase_no':1,'phase_title':'基础洁治与复评','clinical_condition':'检查后由负责牙医确认可实施','responsible_clinic_id':clinic['id'],'clinical_released':True,'estimated_fee':180,'items':[{'standard_id':clean['id'],'planned_quantity':1,'site_description':'教学模拟部位'}]},
        {'phase_no':2,'phase_title':'后续牙位修复','clinical_condition':'基础阶段完成并复评放行','responsible_clinic_id':clinics[1]['id'],'clinical_released':False,'estimated_fee':320,'items':[{'standard_id':repair['id'],'planned_quantity':1,'site_description':'教学模拟牙位26'}]},
        {'phase_no':3,'phase_title':'基础阶段效果复查','clinical_condition':'基础阶段完成后核实效果','responsible_clinic_id':clinic['id'],'clinical_released':False,'estimated_fee':50,'items':[{'standard_id':exam['id'],'planned_quantity':1}]},
        {'phase_no':4,'phase_title':'独立牙位修复评估','clinical_condition':'已核实可独立安排检查','responsible_clinic_id':clinics[1]['id'],'clinical_released':True,'estimated_fee':50,'items':[{'standard_id':exam['id'],'planned_quantity':1}]}], 'dependencies':[[1,2],[1,3]]})
    phase=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=1',[plan['id']]);tomorrow=today+timedelta(days=1);duty=one("SELECT * FROM practice_duty WHERE dentist_id=%s AND clinic_id=%s AND publication_state='published' AND (starts_at AT TIME ZONE 'Asia/Shanghai')::date=%s ORDER BY id LIMIT 1",[dentist,clinic['id'],tomorrow])
    call('patient','UC02',{'action':'book','patient_id':patient['id'],'clinic_id':clinic['id'],'dentist_id':dentist,'duty_id':duty['id'],'operatory_id':op['id'],'starts_at':datetime.combine(tomorrow,time(10),tz).isoformat(),'ends_at':datetime.combine(tomorrow,time(10,30),tz).isoformat(),'standard_ids':[clean['id']],'phase_id':phase['id'],'presenting_request':'教学模拟：按已确认方案接续基础阶段'})
    print('Enhanced synthetic fixtures: 2 available clinics, 3 qualified dentists, 8 standards, actual signed teaching visit/invoice, four-stage branching plan and future continuation appointment; existing records preserved')
