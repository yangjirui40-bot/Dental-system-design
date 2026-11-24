"""Explicit database initialization; never auto-seed patient data in production."""
import os,sys,argparse,getpass
os.environ.setdefault('DJANGO_SETTINGS_MODULE','adc.settings')
import django
django.setup()
from django.db import connection,transaction
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from core.db import insert,one,rows,execute
from core.security import ROLE_CODES

def initialize():
    with transaction.atomic():
        exists=one("SELECT to_regclass('public.patient') AS name")['name']
        if exists:
            count=one("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")['n']
            if count!=58:raise RuntimeError('数据库结构与58表设计不符，请先迁移或选择空库')
            execute((settings.CONTRACTS_DIR/'auth-001.sql').read_text())
            print('Existing schema: 58 tables');return
        execute((settings.CONTRACTS_DIR/'schema.sql').read_text())
        execute((settings.CONTRACTS_DIR/'auth-001.sql').read_text())
    print('Initialized the supplied 58-table PostgreSQL schema')

def reference_quarters():
    year=timezone.localdate().year
    for y in (year,year+1):
        for q in range(1,5):
            start=date(y,3*(q-1)+1,1);end=date(y+1,1,1) if q==4 else date(y,3*q+1,1)
            execute('INSERT INTO fiscal_quarter(calendar_year,quarter_no,starts_on,ends_before) VALUES(%s,%s,%s,%s) ON CONFLICT(calendar_year,quarter_no) DO NOTHING',[y,q,start,end])

def real_profile(prefix,label):
    data={}
    for key,prompt in [('EMPLOYEE_NO','职工编号'),('NAME','姓名'),('BIRTH_DATE','出生日期 YYYY-MM-DD'),('ADDRESS','通讯地址'),('PHONE','联系电话'),('EMAIL','电子邮箱'),('EMPLOYED_FROM','入职日期 YYYY-MM-DD')]:
        value=os.environ.get(prefix+'_'+key,'').strip()
        if not value and sys.stdin.isatty():value=input(label+' · '+prompt+'：').strip()
        if not value:raise RuntimeError('请提供'+prefix+'_'+key+'，或通过终端交互填写')
        data[key]=value
    for key in ['BIRTH_DATE','EMPLOYED_FROM']:data[key]=date.fromisoformat(data[key])
    return dict(zip(['employee_no','full_name','birth_date','home_address','phone','email','employed_from'],[data[k] for k in ['EMPLOYEE_NO','NAME','BIRTH_DATE','ADDRESS','PHONE','EMAIL','EMPLOYED_FROM']]),row_version=1)

def seed(demo=False):
    require_empty=one('SELECT id FROM user_account LIMIT 1')
    if require_empty:print('Accounts already present; seeding skipped');return
    password=os.environ.get('DEMO_PASSWORD') if demo else os.environ.get('ADMIN_PASSWORD')
    if not demo and not password and sys.stdin.isatty():password=getpass.getpass('首位集团负责人密码（至少12位）：')
    if not password or len(password)<12:raise RuntimeError('设置至少12位的DEMO_PASSWORD或ADMIN_PASSWORD')
    admin_profile={};business_profile={}
    if not demo:
        admin_profile=real_profile('ADMIN','首位总部负责人')
        business_profile=real_profile('BUSINESS','首位独立总部业务人员')
        require_different=admin_profile['employee_no']!=business_profile['employee_no']
        if not require_different:raise RuntimeError('负责人和初始业务人员须使用不同的真实职工编号')
        business_password=os.environ.get('BUSINESS_PASSWORD')
        if not business_password and sys.stdin.isatty():business_password=getpass.getpass('首位业务人员密码（至少12位且与负责人不同）：')
        if not business_password or len(business_password)<12 or business_password==password:raise RuntimeError('BUSINESS_PASSWORD须至少12位且与负责人不同')
    now=timezone.now();today=timezone.localdate();tz=ZoneInfo('Asia/Shanghai')
    with transaction.atomic():
        roles={code:insert('access_role',dict(role_code=code,role_name=name)) for code,name in ROLE_CODES.items()}
        boss_data=dict(employee_no='EMP-HQ-001',full_name='陈安德',birth_date=date(1980,1,1),home_address='演示资料',phone='02000000001',email='director@example.invalid',employed_from=date(2020,1,1),row_version=1)
        if not demo:boss_data.update(admin_profile)
        boss=insert('employee',boss_data)
        admin=insert('user_account',dict(employee_id=boss['id'],login_name='director',password_hash=make_password(password),is_enabled=True,created_at=now,account_kind='employee',display_name=boss['full_name']))
        insert('account_scope',dict(account_id=admin['id'],role_id=roles['director']['id'],granted_by=admin['id'],granted_at=now,scope_kind='group'))
        if not demo:
            employee=insert('employee',business_profile)
            account=insert('user_account',dict(employee_id=employee['id'],login_name='business',password_hash=make_password(business_password),is_enabled=True,created_at=now,account_kind='employee',display_name=employee['full_name']))
            insert('account_scope',dict(account_id=account['id'],role_id=roles['business']['id'],granted_by=admin['id'],granted_at=now,scope_kind='group'))
            print('Initialized independent director and business accounts; no patient demo data inserted')
            return
        clinics=[]
        for n,name in enumerate(['广州天河门诊','广州越秀门诊'],1):clinics.append(insert('clinic',dict(clinic_no=f'C{n:03}',clinic_name=name,postal_address='广州市·教学演示地址',phone='0200000000'+str(n),email=f'clinic{n}@example.invalid',floor_area=160,opened_on=date(2020,1,1),row_version=1)))
        employee_accounts={}
        for index,(code,name) in enumerate([('business','何知遥'),('manager','刘思敏'),('finance','陆宁'),('reception','沈清'),('dentist','周明远')],2):
            e=insert('employee',dict(employee_no=f'EMP{index:03}',full_name=name,birth_date=date(1990,1,1),home_address='教学演示地址',phone='1380000000'+str(index),email=code+'@example.invalid',employed_from=date(2020,1,1),row_version=1))
            a=insert('user_account',dict(employee_id=e['id'],login_name=code,password_hash=make_password(password),is_enabled=True,created_at=now,account_kind='employee',display_name=name));employee_accounts[code]=(e,a)
            insert('account_scope',dict(account_id=a['id'],role_id=roles[code]['id'],clinic_id=clinics[0]['id'] if code in ('manager','reception','dentist') else None,scope_kind='clinic' if code in ('manager','reception','dentist') else 'group',granted_by=admin['id'],granted_at=now))
        dentist=employee_accounts['dentist'][0];insert('dentist',dict(id=dentist['id'],professional_no='DEMO-DENTIST-001'))
        manager=employee_accounts['manager'][0];insert('clinic_manager',dict(clinic_id=clinics[0]['id'],employee_id=manager['id'],effective_from=now-timedelta(days=365)))
        p=insert('patient',dict(account_no='P-DEMO-001',full_name='林嘉宁',birth_date=date(1999,4,18),sex_code='female',billing_address='广州市·教学演示地址',phone='13800002068',email='patient@example.invalid',allergy_declaration='unknown',row_version=1,created_at=now))
        for index in range(2):
            kind='patient' if index==0 else 'representative';a=insert('user_account',dict(login_name=kind,password_hash=make_password(password),is_enabled=True,created_at=now,account_kind=kind,patient_id=p['id'] if kind=='patient' else None,display_name='林嘉宁' if kind=='patient' else '林女士'))
            insert('account_scope',dict(account_id=a['id'],role_id=roles[kind]['id'],patient_id=p['id'],scope_kind='self' if kind=='patient' else 'authorized_patient',granted_by=admin['id'],granted_at=now))
            if kind=='representative':
                contact=insert('patient_contact',dict(patient_id=p['id'],full_name='林女士',phone='13800002069',relationship='授权代办人',contact_purpose='agent',recorded_by=manager['id'],recorded_account_id=admin['id'],recorded_at=now));insert('patient_authority',dict(patient_id=p['id'],contact_id=contact['id'],permission_scope='all',evidence_reference='教学演示授权记录',valid_from=now-timedelta(days=1),valid_to=now+timedelta(days=30),verified_by=manager['id'],verified_at=now,authorized_account_id=a['id']))
        for name in ['乳胶','青霉素','局部麻醉剂']:insert('allergy_substance',dict(substance_name=name,substance_category='材料或药物'))
        kind=insert('qualification_kind',dict(qualification_name='综合牙科执业资格',description='教学演示资格'))
        insert('dentist_qualification',dict(dentist_id=dentist['id'],qualification_kind_id=kind['id'],certificate_no='DEMO-QUAL-001',issuing_organisation='教学演示机构',valid_from=date(2020,1,1),verification_result='verified',verified_by=employee_accounts['business'][0]['id'],verified_at=now))
        standards=[]
        for idx,(name,unit,price,duration) in enumerate([('初步检查','次',50,20),('超声洁治','次',180,30),('树脂充填','牙',320,30)],1):
            c=insert('treatment_catalog',dict(treatment_code=f'T{idx:03}',treatment_name=name,is_available=True));s=insert('treatment_standard',dict(treatment_id=c['id'],revision_no=1,treatment_name=name,unit_name=unit,quantity_scale=0,unit_price=price,site_requirement='由牙医核实部位',valid_from=now-timedelta(days=365),approval_state='approved',approved_by=boss['id'],approved_at=now,duration_minutes=duration));insert('standard_qualification',dict(standard_id=s['id'],qualification_kind_id=kind['id']));standards.append(s)
        operatories=[]
        for clinic in clinics:
            for idx in range(1,3):operatories.append(insert('operatory',dict(clinic_id=clinic['id'],operatory_code=f'OP{idx:02}',operatory_name=f'诊疗位{idx:02}',resource_state='active',changed_by=manager['id'],changed_at=now,row_version=1)))
        for days in range(15):
            day=today+timedelta(days=days)
            for clinic in clinics:
                start=datetime.combine(day,time(9),tz);end=datetime.combine(day,time(18),tz);cal=insert('clinic_calendar',dict(clinic_id=clinic['id'],work_date=day,session_no=1,is_open=True,starts_at=start,ends_at=end,confirmed_by=manager['id'],confirmed_at=now,row_version=1))
                if clinic==clinics[0]:
                    d=insert('practice_duty',dict(dentist_id=dentist['id'],clinic_id=clinic['id'],starts_at=start,ends_at=end,publication_state='published',confirmed_by=manager['id'],confirmed_at=now,row_version=1,calendar_id=cal['id']));insert('duty_skill',dict(duty_id=d['id'],qualification_kind_id=kind['id']))
        for q in range(1,5):
            start=date(today.year,3*(q-1)+1,1);end=date(today.year+1,1,1) if q==4 else date(today.year,3*q+1,1)
            if not one('SELECT id FROM fiscal_quarter WHERE calendar_year=%s AND quarter_no=%s',[today.year,q]):insert('fiscal_quarter',dict(calendar_year=today.year,quarter_no=q,starts_on=start,ends_before=end))
    print('Seeded synthetic demo data. Roles: patient representative reception dentist manager business finance director')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--demo',action='store_true');parser.add_argument('--admin',action='store_true');args=parser.parse_args();initialize();reference_quarters()
    if args.demo or args.admin:seed(args.demo)
