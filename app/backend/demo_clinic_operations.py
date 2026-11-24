"""Create traceable, synthetic multi-clinic teaching operations."""
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
DISTRICTS = ('黄埔', '南沙', '从化', '增城')
DOCTORS = ('高书怡','章亦然','谢霁宁','蒋启程','姜语乔','许佳昀','彭文恺','罗意舒',
           '蔡晴川','沈亦乔','周嘉平','任婉和','何景恬','孟昭远','顾秋禾','程知言')
SURNAMES = '郭姚赵孙裴江吴韩蒋梁'
GIVEN_NAMES = ('青禾','乐秋','和宁','景若','澄宇','安乔','芮安','嘉语','知润','静宜','明晞','初然',
               '书玥','淮序','晚晴','时予','晓诺','星桐','南舒','季言','言川','逸飞','雨棠','雨歆')


def must(condition,message):
    if not condition:
        raise RuntimeError(message)


def at(day,hour,minute=0):
    return datetime.combine(day,time(hour,minute),ZONE)


def seed(commit):
    now=timezone.now()
    today=now.astimezone(ZONE).date()
    counts=Counter()
    client=Client(SERVER_NAME='localhost',secure=True)
    with transaction.atomic():
        one("SELECT pg_advisory_xact_lock(hashtextextended('adc-teaching-operations-1',0))")
        must(one("SELECT id FROM patient WHERE account_no='P-DEMO-001' AND email='patient@example.invalid'"),'Original teaching identity missing')
        branch_emails=['clinic1@example.invalid','clinic2@example.invalid']+[f'network-clinic-{i:02}@example.invalid' for i in range(1,5)]
        branches=[one('SELECT * FROM clinic WHERE email=%s AND closed_on IS NULL',[email]) for email in branch_emails]
        must(all(branches),'Original six teaching sites missing or closed')
        staff={}
        for role in ('business','director','reception','manager','finance'):
            account=one('SELECT * FROM user_account WHERE login_name=%s AND is_enabled',[role])
            must(account and one('SELECT id FROM employee WHERE id=%s AND email=%s',[account['employee_id'],role+'@example.invalid']), 'Teaching account guard failed for '+role)
            staff[role]=account
        marker=one('SELECT count(*) AS n FROM patient WHERE email LIKE %s',['training-ops-%@example.invalid'])['n']
        if marker:
            must(marker==len(SURNAMES)*len(GIVEN_NAMES),'Partial teaching operations markers')
            print(json.dumps({'already_seeded':True,'patients':marker}))
            return
        role_ids={r['role_code']:r['id'] for r in rows('SELECT id,role_code FROM access_role')}
        authorization={}
        def call(role,case,scope=None,**payload):
            account=staff[role]
            key=(role,scope)
            if key not in authorization:
                options=scopes(account['id'])
                chosen=next((r for r in options if r['role_code']==role.split(':')[0] and (scope is None or r['clinic_id']==scope)),None)
                must(chosen,f'Missing {role} teaching scope')
                authorization[key]='Bearer '+token(account,chosen['id'])
            response=client.post('/api/use-cases/'+case,json.dumps(payload,default=str),content_type='application/json',
                                 headers={'Authorization':authorization[key],'Idempotency-Key':str(uuid4())})
            result=response.json()
            must(response.status_code==200,f'{role} {case}/{payload.get("action")}: {response.status_code}: {result.get("message")}')
            return result

        def employee(name,email,phone):
            return call('business','UC08',action='employee',full_name=name,birth_date='1991-04-13',
                        home_address='课堂合成资料',email=email,phone=phone,employed_from='2020-01-01')

        def grant(role,account,clinic):
            if any(s['role_code']==role and s['clinic_id']==clinic for s in scopes(account['id'])):
                return
            call('director','UC16',action='grant',account_id=account['id'],role_id=role_ids[role],scope_kind='clinic',clinic_id=clinic)
            counts['clinic_grants']+=1

        for i,district in enumerate(DISTRICTS,1):
            clinic=call('business','UC07',action='save',clinic_name=f'广州{district}门诊',postal_address=f'{district}区 · 课堂示范点',
                        email=f'ops-clinic-{i:02}@example.invalid',phone=f'02000006{i:03}',floor_area=148+i*22,opened_on='2020-01-01')
            branches.append(get('clinic',clinic['id']))
            for position in (1,2,3):
                call('business','UC15',action='operatory',clinic_id=clinic['id'],operatory_code=f'OP{position:02}',
                     operatory_name='综合诊疗位 '+str(position),resource_state='active')
                counts['operatories']+=1
            counts['new_clinics']+=1
        skills=one("SELECT id FROM qualification_kind ORDER BY id LIMIT 1")
        teams={c['id']:[] for c in branches}
        for i,(name,position) in enumerate(zip(DOCTORS,(0,1,2,3,4,5,6,6,6,7,7,7,8,8,9,9)),1):
            clinic=branches[position]['id']
            doctor=employee(name,f'ops-dentist-{i:02}@example.invalid',f'02000007{i:03}')
            professional=f'DEMO-OPS-D{i:02}'
            call('business','UC08',action='dentist',employee_id=doctor['id'],professional_no=professional)
            call('business','UC08',action='qualification',dentist_id=doctor['id'],qualification_kind_id=skills['id'],
                 certificate_no=professional+'-TEACHING',issuing_organisation='课堂合成发证机构',valid_from='2020-01-01',verification_result='verified')
            if not teams[clinic]:
                account=call('business','UC16',action='create',employee_id=doctor['id'],login_name=f'training_ops_dentist_{i:02}',
                             display_name=doctor['full_name'],account_kind='employee',password=uuid4().hex)
                grant('dentist',account,clinic)
                staff['dentist:'+str(clinic)]=get('user_account',account['id'])
            teams[clinic].append(doctor['id'])
            counts['new_doctors']+=1
        for branch in branches:
            for role in ('reception','manager'):
                grant(role,staff[role],branch['id'])

        calendar_cache,duty_cache={},{}
        def calendar(clinic,day):
            key=(clinic,day)
            if key not in calendar_cache:
                item=one("""SELECT * FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s AND is_open
                            AND starts_at<=%s AND ends_at>=%s ORDER BY session_no LIMIT 1""",[clinic,day,at(day,9),at(day,17)])
                if not item and not one('SELECT id FROM clinic_calendar WHERE clinic_id=%s AND work_date=%s',[clinic,day]):
                    item=call('business','UC15',action='calendar',clinic_id=clinic,work_date=day,session_no=1,
                              is_open=True,starts_at=at(day,9),ends_at=at(day,18))
                    counts['open_days']+=1
                calendar_cache[key]=item
            return calendar_cache[key]

        def duty(clinic,doctor,day):
            key=(clinic,doctor,day)
            if key not in duty_cache:
                cal=calendar(clinic,day)
                if not cal:
                    duty_cache[key]=None
                    return None
                start=at(day,9)
                with patch('django.utils.timezone.now',return_value=min(now,start-timedelta(hours=1))):
                    item=call('business','UC09',action='publish',clinic_id=clinic,dentist_id=doctor,calendar_id=cal['id'],
                              starts_at=start,ends_at=at(day,17),qualification_kind_ids=[skills['id']])
                duty_cache[key]=item
                counts['duties']+=1
            return duty_cache[key]

        for clinic,team in teams.items():
            for offset in range(1,25):
                day=today+timedelta(days=offset)
                for i,doctor in enumerate(team):
                    if (offset+i)%7!=0:
                        duty(clinic,doctor,day)

        standards=rows("""SELECT id,treatment_name,unit_price,duration_minutes FROM treatment_standard
                          WHERE approval_state='approved' AND valid_to IS NULL AND valid_from<=%s
                            AND treatment_name IN ('初步检查','超声洁治','树脂充填') ORDER BY id""",[now-timedelta(days=45)])
        must(standards,'Original teaching treatments not available throughout the sample period')
        chairs={c['id']:rows("SELECT id FROM operatory WHERE clinic_id=%s AND resource_state='active' ORDER BY id",[c['id']]) for c in branches}
        must(all(chairs.values()),'Teaching chair missing')
        patients=[]
        allergy=one('SELECT id FROM allergy_substance ORDER BY id LIMIT 1')
        for group,branch in enumerate(branches):
            clinic=branch['id']
            group_patients=[]
            for i,given in enumerate(GIVEN_NAMES):
                unique=group*len(GIVEN_NAMES)+i+1
                person=call('reception','UC01',clinic,action='save',full_name=SURNAMES[group]+given,birth_date=f'{1979+(unique%28)}-{(unique%12)+1:02}-{(unique%27)+1:02}',
                            sex_code='male' if i%2 else 'female',billing_address=branch['postal_address']+' · 教学档案',phone=f'02008{unique:06}',
                            email=f'training-ops-{unique:04}@example.invalid',allergy_declaration='unknown',
                            emergency_name='示范联系人 '+str(unique),emergency_phone=f'02009{unique:06}',emergency_relationship='亲属',
                            identity_confirmed=True,identity_check_basis='课堂资料编排')
                group_patients.append(person['id'])
                counts['patients']+=1
                counts['contacts']+=1
                if i%8==0 and allergy:
                    call('reception','UC01',clinic,action='allergy',id=person['id'],substance_id=allergy['id'],
                         reaction_description='教学模拟申报，待岗位核实',report_source='课堂数据')
                    counts['allergies']+=1
            patients.append(group_patients)

        def visit(patient,clinic,day,standard,state):
            doctor=teams[clinic][0]
            for offset in range(9):
                chosen=day+timedelta(days=offset)
                band=duty(clinic,doctor,chosen)
                if not band or (state!='booked' and chosen>=today):
                    continue
                for minute in range(0,300,30):
                    start=at(chosen,10)+timedelta(minutes=minute)
                    end=start+timedelta(minutes=int(standard['duration_minutes']))
                    if end>at(chosen,17):
                        continue
                    if one("""SELECT id FROM appointment WHERE starts_at<%s AND ends_at>%s AND
                             resolution IN ('booked','arrived','seen') AND (dentist_id=%s OR patient_id=%s)""",[end,start,doctor,patient]):
                        continue
                    op=next((o['id'] for o in chairs[clinic] if not one("""SELECT id FROM appointment WHERE operatory_id=%s
                         AND starts_at<%s AND ends_at>%s AND resolution IN ('booked','arrived','seen')""",[o['id'],end,start])),None)
                    if op is not None:
                        break
                else:
                    continue
                break
            else:
                raise RuntimeError('No complete teaching slot')
            with patch('django.utils.timezone.now',return_value=min(now,start-timedelta(hours=3))):
                ap=call('reception','UC02',clinic,action='book',patient_id=patient,clinic_id=clinic,dentist_id=doctor,
                        duty_id=band['id'],operatory_id=op,starts_at=start,ends_at=end,standard_ids=[standard['id']],
                        presenting_request='教学演示 · '+standard['treatment_name'])
            counts['appointments']+=1
            if state=='booked':
                counts['future_bookings']+=1
                return
            if state=='no_show':
                call('reception','UC04',clinic,action='no_show',appointment_id=ap['id'],reason='教学记录：核对后确认未到')
                counts['no_shows']+=1
                return
            with patch('django.utils.timezone.now',return_value=start),patch('django.utils.timezone.localdate',return_value=chosen):
                if state=='cancelled':
                    call('reception','UC03',clinic,action='cancel',id=ap['id'],row_version=ap['row_version'],
                         initiator_kind='patient',reason='教学模拟：患者行程变化')
                    counts['cancelled']+=1
                    return
                call('reception','UC04',clinic,action='arrive',appointment_id=ap['id'])
                visit=call('dentist:'+str(clinic),'UC04',clinic,action='start',appointment_id=ap['id'],identity_confirmed=True,allergy_confirmed=True)
            note={k:'合成教学业务记录' for k in ('chief_complaint','present_illness','medical_history','examination_summary','tests_summary',
                                                   'diagnosis_summary','management_summary','aftercare','allergy_review')}
            with patch('django.utils.timezone.now',return_value=end),patch('django.utils.timezone.localdate',return_value=chosen):
                call('dentist:'+str(clinic),'UC05',clinic,action='sign',encounter_id=visit['id'],**note,consent_scope='课堂模拟同意',
                     evidence_reference='课程合成凭据',treatments=[{'standard_id':standard['id'],'actual_quantity':1,'charged_unit_price':standard['unit_price'],
                     'implementation_result':'performed','site_description':'合成牙位'}])
            must(one('SELECT id FROM invoice WHERE encounter_id=%s',[visit['id']]),'Missing generated teaching invoice')
            counts['invoices']+=1

        quarter=one('SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[today,today])
        for group,branch in enumerate(branches):
            clinic=branch['id']
            for i,patient in enumerate(patients[group]):
                state='cancelled' if i%9==6 else 'no_show' if i%9==7 else 'signed'
                visit(patient,clinic,today-timedelta(days=31-(i%16)),standards[(group+i)%len(standards)],state)
                visit(patient,clinic,today+timedelta(days=1+i%13),standards[i%len(standards)],'booked')
            for patient in patients[group][:3]:
                other=branches[(group+1)%len(branches)]['id']
                visit(patient,other,today+timedelta(days=15),standards[0],'booked')
                counts['cross_clinic_visits']+=1
            for index,category in enumerate(('supplies','operating')):
                amount=120+group*25+index*75
                revision=call('finance','UC11',action='source',source_document_no=f'OPS-TEACHING-{group+1:02}-{index+1}',cost_category=category,
                              document_date=today,evidence_reference='课堂合成门店费用',source_amount=amount,allocations=[{'quarter_id':quarter['id'],
                              'clinic_id':clinic,'dentist_id':teams[clinic][0],'allocated_amount':amount,'allocation_basis':'模拟门店凭据'}])
                allocation=one('SELECT id FROM cost_allocation WHERE cost_revision_id=%s',[revision['id']])
                if index==0:
                    call('manager','UC11',clinic,action='review',id=allocation['id'],approved=True)
                counts['cost_sources']+=1
        if not commit:
            transaction.set_rollback(True)
        print(json.dumps(dict(committed=commit,**counts),ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--teaching-only',action='store_true',required=True)
    parser.add_argument('--commit',action='store_true')
    seed(parser.parse_args().commit)
