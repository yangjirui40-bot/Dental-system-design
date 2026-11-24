"""Populate additional linked teaching branches through the business use cases."""
import argparse
from collections import Counter
from datetime import datetime, time, timedelta
import json
import os
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE','adc.settings')
django.setup()

from django.db import transaction
from django.test import Client
from django.utils import timezone

from core.db import get, one, rows
from core.security import scopes, token

ZONE = ZoneInfo('Asia/Shanghai')
BRANCHES = (
    ('广州海珠门诊','海珠区 · 江南西教学点'),
    ('广州荔湾门诊','荔湾区 · 西关教学点'),
    ('广州番禺门诊','番禺区 · 市桥教学点'),
    ('广州白云门诊','白云区 · 云城教学点'),
)
NAMES = ('梁若宁','方景和','周澄','颜书远','谭嘉宜','赵文清','苏映秋','陆怀远','林芷晴')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def at(day,hour,minute=0):
    return datetime.combine(day,time(hour,minute),ZONE)


def seed(commit):
    now = timezone.now()
    today = now.astimezone(ZONE).date()
    client = Client(SERVER_NAME='localhost',secure=True)
    totals = Counter()
    with transaction.atomic():
        one("SELECT pg_advisory_xact_lock(hashtextextended('adc-teaching-network-1',0))")
        branches = rows("SELECT * FROM clinic WHERE email IN ('clinic1@example.invalid','clinic2@example.invalid') ORDER BY clinic_no")
        patients = rows("SELECT * FROM patient WHERE account_no='P-DEMO-001' AND email='patient@example.invalid'")
        require(len(branches)==2 and len(patients)==1,'Original teaching clinic or patient markers missing')
        patient = patients[0]
        users = {}
        for role in ('patient','business','director','finance'):
            a = one('SELECT * FROM user_account WHERE login_name=%s AND is_enabled',[role])
            require(a, 'Missing '+role)
            if role=='patient':
                require(a['patient_id']==patient['id'],'Teaching patient changed')
            else:
                require(one('SELECT id FROM employee WHERE id=%s AND email=%s',[a['employee_id'],role+'@example.invalid']), 'Teaching role mismatch')
            users[role]=a

        def call(role, case, **payload):
            account = users[role]
            scope = next(s for s in scopes(account['id']) if s['role_code']==role.split(':')[0])
            response = client.post('/api/use-cases/'+case,json.dumps(payload,default=str),content_type='application/json',
                                   headers={'Authorization':'Bearer '+token(account,scope['id']),'Idempotency-Key':str(uuid4())})
            result = response.json()
            require(response.status_code==200,f"{case}/{payload.get('action')} failed ({response.status_code}): {result.get('message')}")
            return result

        def sample_cross_clinic():
            first, second = [row['id'] for row in branches[:2]]
            doctor = one("SELECT id FROM dentist WHERE professional_no='DEMO-NET-D01'")['id']
            if one('SELECT id FROM practice_duty WHERE clinic_id=%s AND dentist_id=%s', [first,doctor]):
                return
            skill = one("SELECT qualification_kind_id FROM dentist_qualification WHERE dentist_id=%s AND verification_result='verified' ORDER BY id LIMIT 1",[doctor])
            shifts = []
            for offset in (5,12,19):
                day=today+timedelta(days=offset)
                if one("""SELECT id FROM practice_duty WHERE dentist_id=%s AND publication_state='published'
                          AND starts_at<%s AND ends_at>%s""",[doctor,at(day,18),at(day,9)]):
                    continue
                morning = one("""SELECT id FROM clinic_calendar WHERE clinic_id=%s AND is_open AND starts_at<=%s
                                AND ends_at>=%s ORDER BY session_no LIMIT 1""",[second,at(day,9),at(day,12)])
                afternoon = one("""SELECT id FROM clinic_calendar WHERE clinic_id=%s AND is_open AND starts_at<=%s
                                  AND ends_at>=%s ORDER BY session_no LIMIT 1""",[first,at(day,14),at(day,17)])
                if morning and afternoon:
                    shifts.append((day,morning['id'],afternoon['id']))
            require(shifts,'No eligible teaching day for the cross-clinic example')
            for source,target in ((second,first),(first,second)):
                exists = one("""SELECT id FROM travel_rule WHERE from_clinic_id=%s AND to_clinic_id=%s
                                AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s)""",
                              [source,target,today,today+timedelta(days=21)])
                if not exists:
                    call('business','UC09',action='travel-rule',from_clinic_id=source,to_clinic_id=target,
                         minimum_minutes=60,valid_from=today,confirmation_basis='教学示例：双向转场各留60分钟')
            for day,morning,afternoon in shifts:
                args={'action':'publish','dentist_id':doctor,'qualification_kind_ids':[skill['qualification_kind_id']]}
                call('business','UC09',**args,clinic_id=second,calendar_id=morning,starts_at=at(day,9),ends_at=at(day,12))
                call('business','UC09',**args,clinic_id=first,calendar_id=afternoon,starts_at=at(day,14),ends_at=at(day,17))
                totals['cross_clinic_days']+=1
                totals['cross_clinic_duties']+=2

        markers = one("SELECT count(*) AS n FROM clinic WHERE email LIKE %s",["network-clinic-%@example.invalid"])['n']
        if markers:
            require(markers==len(BRANCHES),'Partial teaching network already exists')
            new_people=one("SELECT count(*) AS n FROM dentist WHERE professional_no LIKE %s",["DEMO-NET-D%"])['n']
            require(new_people==len(NAMES),'Teaching roster markers incomplete')
            sample_cross_clinic()
            if not commit:
                transaction.set_rollback(True)
            print(json.dumps({'already_seeded':True,'new_branches':markers,'new_doctors':new_people,'committed':commit,**totals}))
            return
        role_ids={r['role_code']:r['id'] for r in rows('SELECT id,role_code FROM access_role')}
        qualification = one("SELECT id FROM qualification_kind ORDER BY id LIMIT 1")
        for i,(name,address) in enumerate(BRANCHES,1):
            row = call('business','UC07',action='save',clinic_name=name,postal_address=address,
                       email=f'network-clinic-{i:02}@example.invalid',phone=f'02000004{i:03}',floor_area=155+i*18,opened_on='2021-01-01')
            branches.append(get('clinic',row['id']))
            totals['new_branches']+=1
            for j in (1,2):
                call('business','UC15',action='operatory',clinic_id=row['id'],operatory_code=f'OP{j:02}',
                     operatory_name='综合诊疗位 '+str(j),resource_state='active')
                totals['operatories']+=1
        team={c['id']:[] for c in branches}
        for code,index in (('DEMO-DENTIST-001',0),('DEMO-26-DOCTOR-1',0),('DEMO-26-DOCTOR-2',1)):
            doctor=one('SELECT id FROM dentist WHERE professional_no=%s',[code])
            require(doctor, 'Existing teaching dentist missing: '+code)
            team[branches[index]['id']].append(doctor['id'])

        def employee(name,email,phone):
            return call('business','UC08',action='employee',full_name=name,birth_date='1990-05-18',
                        home_address='合成教学资料',phone=phone,email=email,employed_from='2021-01-01')

        def grant(employee,role,clinic,handle):
            account=call('business','UC16',action='create',employee_id=employee['id'],login_name=handle,
                         display_name=employee['full_name'],account_kind='employee',password=uuid4().hex)
            call('director','UC16',action='grant',account_id=account['id'],role_id=role_ids[role],scope_kind='clinic',clinic_id=clinic)
            users[role+':'+str(clinic)] = get('user_account',account['id'])

        for index,(name,branch_index) in enumerate(zip(NAMES,(1,2,2,3,3,4,4,5,5)),1):
            staff=employee(name,f'network-dentist-{index:02}@example.invalid',f'02000005{index:03}')
            professional=f'DEMO-NET-D{index:02}'
            call('business','UC08',action='dentist',employee_id=staff['id'],professional_no=professional)
            call('business','UC08',action='qualification',dentist_id=staff['id'],qualification_kind_id=qualification['id'],
                 certificate_no=professional+'-TEACHING',issuing_organisation='模拟发证机构',
                 valid_from='2021-01-01',verification_result='verified')
            clinic=branches[branch_index]['id']
            team[clinic].append(staff['id'])
            if index in (2,4,6,8):
                grant(staff,'dentist',clinic,'training_network_dentist_'+str(index))
            totals['new_doctors']+=1

        def publish(clinic,doctor,day,start_hour,end_hour,calendar):
            start,end=at(day,start_hour),at(day,end_hour)
            match=one("""SELECT * FROM practice_duty WHERE dentist_id=%s AND publication_state='published'
                        AND starts_at<%s AND ends_at>%s ORDER BY starts_at LIMIT 1""",[doctor,end,start])
            if match:
                return match if match['clinic_id']==clinic else None
            with patch('django.utils.timezone.now', return_value=min(now,start-timedelta(hours=1))):
                duty=call('business','UC09',action='publish',clinic_id=clinic,dentist_id=doctor,
                          calendar_id=calendar['id'],starts_at=start,ends_at=end,
                          qualification_kind_ids=[qualification['id']])
            totals['published_duties']+=1
            return get('practice_duty',duty['id'])

        def open_day(clinic,day):
            cal=one('SELECT * FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s AND is_open ORDER BY session_no LIMIT 1',[clinic,day])
            if cal:
                return cal if cal['starts_at']<=at(day,9) and cal['ends_at']>=at(day,17) else None
            blocked=one('SELECT id FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s',[clinic,day])
            if blocked:
                return None
            with patch('django.utils.timezone.now',return_value=min(now,at(day,8))):
                cal=call('business','UC15',action='calendar',clinic_id=clinic,work_date=day,session_no=1,
                         is_open=True,starts_at=at(day,9),ends_at=at(day,18))
            totals['clinic_days']+=1
            return get('clinic_calendar',cal['id'])

        for offset in range(21):
            day=today+timedelta(days=offset)
            for branch in branches:
                clinic=branch['id']
                calendar=open_day(clinic,day)
                if not calendar:
                    continue
                doctor_ids=team[clinic]
                for position,doctor in enumerate(doctor_ids):
                    # Alternate full-day coverage and split starts so schedules are readable.
                    if (offset+position)%7==6:
                        continue
                    start_hour,end_hour=(9,17) if (offset+position)%4 else (10,16)
                    publish(clinic,doctor,day,start_hour,end_hour,calendar)

        sample_cross_clinic()

        quarter=one('SELECT * FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[today,today])
        exam_rows=rows("""SELECT id,treatment_name,unit_price,duration_minutes,valid_from FROM treatment_standard
                          WHERE approval_state='approved' AND treatment_name IN ('初步检查','超声洁治','树脂充填')
                          AND valid_to IS NULL ORDER BY id""")
        require(quarter and exam_rows,'Original quarter and teaching standards required')
        history=[today-timedelta(days=n) for n in (32,30,28,26,15,13,11,9)]
        history=[max(d,quarter['starts_on']+timedelta(days=1+i//3)) for i,d in enumerate(history)]
        for index,branch in enumerate(branches[2:]):
            clinic=branch['id']
            operator=one("SELECT id FROM operatory WHERE clinic_id=%s AND resource_state='active' ORDER BY id LIMIT 1",[clinic])
            for cycle in (0,1):
                day=history[cycle*4+index]
                if day>=today:
                    continue
                start=at(day,11,index*10)
                exam=exam_rows[(index+cycle)%len(exam_rows)]
                if exam['valid_from']>start:
                    continue
                calendar=open_day(clinic,day)
                duty=publish(clinic,team[clinic][0],day,9,17,calendar)
                end=start+timedelta(minutes=exam['duration_minutes'])
                with patch('django.utils.timezone.now',return_value=start-timedelta(hours=2)),patch('django.utils.timezone.localdate',return_value=day):
                    ap=call('patient','UC02',action='book',clinic_id=clinic,patient_id=patient['id'],
                            dentist_id=team[clinic][0],operatory_id=operator['id'],duty_id=duty['id'],starts_at=start,ends_at=end,
                            standard_ids=[exam['id']],presenting_request='集团教学样本 · '+exam['treatment_name'])
                totals['historical_appointments']+=1
                with patch('django.utils.timezone.now',return_value=start),patch('django.utils.timezone.localdate',return_value=day):
                    if cycle==0 and index%2:
                        call('patient','UC03',action='cancel',id=ap['id'],row_version=ap['row_version'],reason='教学模拟行程变化')
                        continue
                    role='dentist:'+str(clinic)
                    call('patient','UC04',action='arrive',appointment_id=ap['id'])
                    visit=call(role,'UC04',action='start',appointment_id=ap['id'],identity_confirmed=True,allergy_confirmed=True)
                    note = {field:'教学模拟材料，无真实诊疗效力' for field in (
                        'chief_complaint','present_illness','medical_history','examination_summary','tests_summary',
                        'diagnosis_summary','management_summary','aftercare','allergy_review',
                    )}
                    call(role,'UC05',action='sign',encounter_id=visit['id'],**note,consent_scope='合成课程样本',
                         evidence_reference='课堂模拟同意',treatments=[{'standard_id':exam['id'],'actual_quantity':1,
                         'charged_unit_price':exam['unit_price'],'implementation_result':'performed','site_description':'合成演示部位'}])
                    require(one('SELECT id FROM invoice WHERE encounter_id=%s',[visit['id']]),'Missing signed teaching invoice')
                    totals['signed_invoices']+=1
            amount=95+index*25
            call('finance','UC11',action='source',source_document_no=f'ADC-NET-COST-{index+1:02}',cost_category='supplies',
                 document_date=today,evidence_reference='教学集团模拟费用',source_amount=amount,allocations=[{
                     'quarter_id':quarter['id'],'clinic_id':clinic,'dentist_id':team[clinic][0],
                     'allocated_amount':amount,'allocation_basis':'模拟门店领用凭据',
                 }])
            totals['pending_cost_sources']+=1
        if not commit:
            transaction.set_rollback(True)
        print(json.dumps(dict(committed=commit,**totals),ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--teaching-only',action='store_true',required=True)
    parser.add_argument('--commit',action='store_true')
    seed(parser.parse_args().commit)
