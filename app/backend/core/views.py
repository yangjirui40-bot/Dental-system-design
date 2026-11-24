import json
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import check_password, make_password
from django.conf import settings
from .db import rows, one, get, SCHEMA
from .security import authenticate, scopes, token, require, ROLE_CODES,client_surface,account_surface,surface_scopes
from .http import endpoint, mutation
from . import booking, clinical, administration, finance
DESIGN=json.loads((settings.CONTRACTS_DIR/'design.json').read_text())
NAME_TO_CODE={v:k for k,v in ROLE_CODES.items()}
CASE_ROLES={u['id']:[NAME_TO_CODE[a] for a in u['actors']] for u in DESIGN['cases']}
HANDLERS={'UC01':administration.patient_action,'UC02':booking.book,'UC03':booking.change,'UC04':booking.encounter_action,
 'UC05':clinical.save_treatment,'UC06':clinical.issue_invoice,'UC07':administration.clinic_action,'UC08':administration.dentist_action,
 'UC09':administration.duty_action,'UC10':administration.standard_action,'UC11':finance.cost_action,'UC12':finance.report_action,
 'UC13':clinical.plan_action,'UC15':administration.resources_action,'UC16':administration.accounts_action}

@endpoint
def health(request,b):
    return {'status':'ok','database':one('SELECT current_setting(\'server_version\') AS version')['version']}

@csrf_exempt
@endpoint
def login(request,b):
    require(request.method=='POST','请使用POST',405)
    account=one('SELECT * FROM user_account WHERE login_name=%s',[str(b.get('login_name',''))])
    # Perform a hash check for unknown users too, without disclosing identity.
    matched=check_password(str(b.get('password','')),account['password_hash'] if account else make_password('unavailable-identity'))
    require(account and account['is_enabled'] and matched,'账号或密码不正确',401)
    surface=client_surface(b.get('client_surface') or request.headers.get('X-ADC-Surface') or account_surface(account))
    available=surface_scopes(account['id'],surface)
    require(available,'患者及代办账号请使用患者小程序；工作人员请使用诊所管理系统，且须有有效岗位授权',403)
    return {'token':token(account,available[0]['id'],surface=surface),'application_surface':surface,'account':{k:account[k] for k in ['id','login_name','display_name','account_kind','patient_id']},'scopes':available,'scope':available[0]}

@csrf_exempt
@endpoint
def switch(request,b):
    require(request.method=='POST','请使用POST',405);actor=authenticate(request);available=surface_scopes(actor.id,actor.surface);chosen=next((s for s in available if s['id']==int(b['scope_id'])),None);require(chosen,'岗位授权不存在或不属于当前入口',403)
    require(not b.get('client_surface') or b['client_surface']==actor.surface,'不能通过切换身份更改服务入口',403)
    return {'token':token(actor.account,chosen['id'],actor.external_binding_id,actor.surface),'scope':chosen,'application_surface':actor.surface}

@csrf_exempt
@endpoint
def usecase(request,b,code):
    require(request.method=='POST','请使用POST',405);actor=authenticate(request);require(code in CASE_ROLES,'用例不存在',404);actor.allow(*CASE_ROLES[code]);require(code in HANDLERS,'此用例通过查询办理',405)
    for key in ['identity_confirmed','allergy_confirmed','is_open','approved','supplies_complete','operating_complete','clinical_confirmed','retire_previous']:
        if key in b:require(isinstance(b[key],bool),'确认字段必须为布尔值',400)
    return mutation(actor,code,request,b,lambda:HANDLERS[code](actor,b))

def patient_ids(actor):
    if actor.role=='patient':return [actor.account['patient_id']]
    if actor.role=='representative':
        require(one('SELECT id FROM patient_authority WHERE authorized_account_id=%s AND patient_id=%s AND revoked_at IS NULL AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())',[actor.id,actor.scope['patient_id']]),'患者授权已失效',403)
        return [actor.scope['patient_id']]
    if actor.role=='dentist':return [r['patient_id'] for r in rows('SELECT DISTINCT patient_id FROM appointment WHERE dentist_id=%s UNION SELECT patient_id FROM treatment_plan WHERE created_by=%s',[actor.employee,actor.employee])]
    return None

@endpoint
def workspace(request,b):
    actor=authenticate(request);role=actor.role;personal=role in ('patient','representative');clinical_role=role=='dentist';group=actor.scope['scope_kind']=='group'
    clinic=None if group or personal else actor.clinic
    clinics=rows('SELECT id,clinic_no,clinic_name,postal_address,phone,email,floor_area,opened_on,closed_on,row_version FROM clinic WHERE (%s::bigint IS NULL OR id=%s) ORDER BY id',[clinic,clinic])
    if personal:
        for c in clinics:
            c.pop('floor_area',None)
            c.pop('email',None)
    patients=[]
    if role in ('patient','representative','dentist'):
        ids=patient_ids(actor);patients=rows('SELECT * FROM patient WHERE id=ANY(%s::bigint[]) ORDER BY id LIMIT 200',[ids])
    elif role=='reception':patients=rows('SELECT * FROM patient ORDER BY id DESC LIMIT 200')
    elif role=='manager':patients=rows('SELECT DISTINCT p.* FROM patient p JOIN appointment a ON a.patient_id=p.id WHERE a.clinic_id=%s ORDER BY p.id DESC LIMIT 200',[clinic])
    ids=[p['id'] for p in patients]
    apps=[]
    if role in ('patient','representative','dentist','reception','manager'):
        apps=rows("""SELECT a.*,p.full_name AS patient_name,e.full_name AS dentist_name,c.clinic_name FROM appointment a
          JOIN patient p ON p.id=a.patient_id JOIN employee e ON e.id=a.dentist_id JOIN clinic c ON c.id=a.clinic_id
          WHERE (%s::bigint IS NULL OR a.clinic_id=%s) AND (%s::boolean=false OR a.patient_id=ANY(%s::bigint[])) AND (%s::bigint IS NULL OR a.dentist_id=%s)
          ORDER BY a.id DESC LIMIT 200""",[clinic,clinic,personal,ids,actor.employee if clinical_role else None,actor.employee if clinical_role else None])
    app_ids=[a['id'] for a in apps];encounters=rows('SELECT e.*,a.patient_id,a.clinic_id,a.dentist_id,p.full_name AS patient_name,(SELECT n.signature_state FROM clinical_note n WHERE n.encounter_id=e.id ORDER BY n.revision_no DESC LIMIT 1) AS latest_signature_state FROM encounter e JOIN appointment a ON a.id=e.appointment_id JOIN patient p ON p.id=a.patient_id WHERE a.id=ANY(%s::bigint[]) ORDER BY e.id DESC',[app_ids])
    invoice_rows=[]
    can_invoice=role!='representative' or one("SELECT id FROM patient_authority WHERE authorized_account_id=%s AND patient_id=%s AND permission_scope IN ('all','invoices') AND revoked_at IS NULL AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())",[actor.id,actor.scope['patient_id']])
    if role in ('patient','representative','dentist','reception','manager','finance','director') and can_invoice:
        invoice_rows=rows("""SELECT i.*,r.id AS revision_id,r.revision_no,r.total_amount,r.issued_by,r.issued_at,r.validity,p.full_name AS patient_name,c.clinic_name
        FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id AND r.validity='current' JOIN encounter e ON e.id=i.encounter_id JOIN appointment a ON a.id=e.appointment_id JOIN patient p ON p.id=a.patient_id JOIN clinic c ON c.id=a.clinic_id
        WHERE (%s::bigint IS NULL OR a.clinic_id=%s) AND (%s::boolean=false OR a.patient_id=ANY(%s::bigint[])) AND (%s::bigint IS NULL OR a.dentist_id=%s) ORDER BY i.id DESC LIMIT 200""",[clinic,clinic,personal,ids,actor.employee if clinical_role else None,actor.employee if clinical_role else None])
        if role in ('finance','director'):
            for i in invoice_rows:i.pop('patient_name',None)
    menu=[{'code':u['id'],'name':u['name']} for u in DESIGN['cases'] if role in CASE_ROLES[u['id']]]
    resources={'clinics':clinics,'patients':patients,'appointments':apps,'encounters':encounters,'invoices':invoice_rows,
      'dentists':rows('SELECT d.id,e.full_name,d.professional_no FROM dentist d JOIN employee e ON e.id=d.id ORDER BY d.id'),
      'standards':rows("SELECT * FROM treatment_standard WHERE approval_state='approved' OR (%s::boolean AND approval_state='retired') ORDER BY treatment_id,revision_no DESC",[role=='dentist']),
      'quarters':rows('SELECT * FROM fiscal_quarter ORDER BY starts_on DESC'),
      'allergy_substances':rows('SELECT * FROM allergy_substance ORDER BY id') if patients else []}
    for key,sql,args in [
      ('phases',"SELECT p.*,s.id AS specification_id,s.phase_title,s.clinical_condition,s.responsible_clinic_id,t.patient_id,t.plan_no FROM treatment_phase p JOIN treatment_plan t ON t.id=p.plan_id JOIN phase_specification s ON s.phase_id=p.id JOIN plan_revision r ON r.id=s.plan_revision_id AND (r.confirmation_state='confirmed' OR %s::boolean) WHERE t.patient_id=ANY(%s::bigint[]) AND (%s::boolean=false OR r.id=(SELECT id FROM plan_revision latest WHERE latest.plan_id=t.id ORDER BY latest.revision_no DESC LIMIT 1)) ORDER BY p.id",[role=='dentist',ids,role=='dentist']),
      ('followups','SELECT * FROM followup_task WHERE patient_id=ANY(%s::bigint[]) AND (%s::bigint IS NULL OR responsible_clinic_id=%s) ORDER BY next_contact_at',[ids,clinic,clinic]),
      ('contacts','SELECT * FROM patient_contact WHERE patient_id=ANY(%s::bigint[]) ORDER BY id',[ids]),
      ('authorities','SELECT * FROM patient_authority WHERE patient_id=ANY(%s::bigint[]) ORDER BY id',[ids])]:resources[key]=rows(sql,args)
    resources['phase_items']=rows('SELECT pi.*,s.phase_title FROM phase_item pi JOIN phase_specification s ON s.id=pi.phase_specification_id JOIN treatment_phase p ON p.id=s.phase_id JOIN treatment_plan t ON t.id=p.plan_id WHERE t.patient_id=ANY(%s::bigint[]) ORDER BY pi.id',[ids]) if clinical_role else []
    if not personal:
        resources.update(calendars=rows('SELECT * FROM clinic_calendar WHERE (%s::bigint IS NULL OR clinic_id=%s) ORDER BY work_date DESC LIMIT 200',[clinic,clinic]),operatories=rows('SELECT * FROM operatory WHERE (%s::bigint IS NULL OR clinic_id=%s) ORDER BY id',[clinic,clinic]),duties=rows('SELECT * FROM practice_duty WHERE (%s::bigint IS NULL OR clinic_id=%s) ORDER BY starts_at DESC LIMIT 200',[clinic,clinic]),qualification_kinds=rows('SELECT * FROM qualification_kind ORDER BY id'))
    if role=='manager':resources['employees']=rows("SELECT DISTINCT e.id,e.employee_no,e.full_name,e.employed_from,e.employed_to FROM employee e JOIN user_account u ON u.employee_id=e.id JOIN account_scope s ON s.account_id=u.id JOIN access_role r ON r.id=s.role_id WHERE u.is_enabled AND s.revoked_at IS NULL AND r.role_code IN ('reception','manager') AND (s.scope_kind='group' OR s.clinic_id=%s) ORDER BY e.id",[clinic])
    if role in ('business','director'):
        resources.update(catalog=rows('SELECT * FROM treatment_catalog ORDER BY id'),standard_drafts=rows("SELECT * FROM treatment_standard WHERE approval_state='draft' ORDER BY id"),employees=rows('SELECT * FROM employee ORDER BY id'),qualifications=rows('SELECT * FROM dentist_qualification ORDER BY id'))
    if role in ('finance','manager','director'):
        resources.update(cost_sources=rows('SELECT s.* FROM cost_source s WHERE %s::bigint IS NULL OR EXISTS(SELECT 1 FROM cost_revision r JOIN cost_allocation a ON a.cost_revision_id=r.id WHERE r.cost_source_id=s.id AND a.clinic_id=%s) ORDER BY s.id DESC LIMIT 200',[clinic,clinic]),cost_revisions=rows('SELECT r.* FROM cost_revision r WHERE %s::bigint IS NULL OR EXISTS(SELECT 1 FROM cost_allocation a WHERE a.cost_revision_id=r.id AND a.clinic_id=%s) ORDER BY r.id DESC LIMIT 200',[clinic,clinic]),allocations=rows('SELECT * FROM cost_allocation WHERE (%s::bigint IS NULL OR clinic_id=%s) ORDER BY id DESC LIMIT 200',[clinic,clinic]),submissions=rows('SELECT * FROM quarter_submission WHERE (%s::bigint IS NULL OR clinic_id=%s) ORDER BY id DESC LIMIT 200',[clinic,clinic]),reports=rows('SELECT id,quarter_id,revision_no,confirmation_state FROM quarter_report ORDER BY id DESC LIMIT 100') if role=='manager' else rows('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 100'))
    if role in ('reception','business','director'):
        resources.update(accounts=rows("SELECT id,login_name,display_name,account_kind,employee_id,patient_id,is_enabled FROM user_account WHERE (%s::boolean=false OR account_kind IN ('patient','representative')) ORDER BY id LIMIT 200",[role=='reception']),roles=rows("SELECT * FROM access_role WHERE %s::boolean=false OR role_code IN ('patient','representative') ORDER BY id",[role=='reception']))
    if role in ('business','director'):
        resources['account_patients']=rows('SELECT id,account_no,full_name FROM patient ORDER BY id DESC LIMIT 200')
    if role in ('business','director'):resources['scopes']=rows('SELECT * FROM account_scope ORDER BY id DESC LIMIT 200')
    names={r['id']:r['full_name'] for r in resources['dentists']};cn={r['id']:r['clinic_name'] for r in clinics};pn={r['id']:r['full_name'] for r in patients};qn={r['id']:r['qualification_name'] for r in resources.get('qualification_kinds',[])}
    for d in resources.get('duties',[]):d['label']=f"{names.get(d['dentist_id'],'牙医')} · {cn.get(d['clinic_id'],'承接门店')}"
    for c in resources.get('calendars',[]):c['label']=f"{cn.get(c['clinic_id'],'门店')} · {c['work_date']} · 时段{c['session_no']}"
    for q in resources.get('qualifications',[]):q['label']=f"{names.get(q['dentist_id'],'牙医')} · {qn.get(q['qualification_kind_id'],'专业资格')} · {q['certificate_no'] or '待核对证照编号'}"
    for a in resources.get('allocations',[]):a['label']=f"{names.get(a['dentist_id'],'牙医')} · {cn.get(a['clinic_id'],'门店')} · ¥{a['allocated_amount']}"
    for r in resources.get('cost_revisions',[]):r['label']=f"费用来源修订 {r['revision_no']} · ¥{r['source_amount']}"
    for s in resources.get('submissions',[]):s['label']=f"{names.get(s['dentist_id'],'牙医')} · {cn.get(s['clinic_id'],'门店')} · 费用齐备声明"
    quarters={q['id']:f"{q['calendar_year']}年第{q['quarter_no']}季度" for q in resources['quarters']}
    for r in resources.get('reports',[]):r['label']=f"{quarters.get(r['quarter_id'],'季度经营')} · 版本{r['revision_no']}"
    for f in resources.get('followups',[]):f['label']=f"{pn.get(f['patient_id'],'患者')} · 治疗接续待约"
    for s in resources.get('scopes',[]):
        account=next((a for a in resources.get('accounts',[]) if a['id']==s['account_id']),{});r=next((a for a in resources.get('roles',[]) if a['id']==s['role_id']),{});s['label']=f"{account.get('display_name','实际账号')} · {r.get('role_name','岗位')}"
    capabilities={'can_book':role=='patient','can_view_stages':role=='patient','can_view_invoices':role=='patient','can_edit_profile':role=='patient'}
    if personal:
        for phase in resources.get('phases',[]):
            phase.pop('clinical_condition',None);phase.pop('origin_encounter_id',None)
    if role=='representative':
        permissions={r['permission_scope'] for r in rows('SELECT permission_scope FROM patient_authority WHERE patient_id=%s AND authorized_account_id=%s AND revoked_at IS NULL AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())',[actor.scope['patient_id'],actor.id])}
        def allowed(permission):return 'all' in permissions or permission in permissions
        capabilities={'can_book':allowed('booking'),'can_view_stages':allowed('booking'),'can_view_invoices':allowed('invoices'),'can_edit_profile':allowed('profile')}
        menu=[m for m in menu if (m['code']=='UC01' and allowed('profile')) or (m['code'] in ('UC02','UC03','UC04') and allowed('booking')) or (m['code']=='UC14' and (allowed('booking') or allowed('invoices')))]
        if not allowed('profile'):resources['patients']=[{k:p[k] for k in ['id','account_no','full_name']} for p in patients]
        if not allowed('booking'):
            for key in ['appointments','encounters','phases','followups']:resources[key]=[]
        resources['authorities']=[a for a in resources['authorities'] if a['authorized_account_id']==actor.id]
        if not allowed('profile'):
            own_contacts={a['contact_id'] for a in resources['authorities']};resources['contacts']=[c for c in resources['contacts'] if c['id'] in own_contacts]
    return {'account':{k:actor.account[k] for k in ['id','login_name','display_name','account_kind','patient_id']},'scope':actor.scope,'scopes':surface_scopes(actor.id,actor.surface),'application_surface':actor.surface,'menu':menu,'resources':resources,'server_time':timezone_string(),'capabilities':capabilities,'list_limit':200}

def timezone_string():
    from django.utils import timezone
    return timezone.now()

@endpoint
def slot_list(request,b):
    actor=authenticate(request)
    if request.GET.get('appointment_id'):
        from .presentation import permitted_appointment
        original=permitted_appointment(actor,int(request.GET['appointment_id']))
        actor.allow(*CASE_ROLES['UC03'])
        require(original['patient_id']==int(request.GET.get('patient_id',0)),'改约患者不符',403)
    else:actor.allow(*CASE_ROLES['UC02'])
    return {'slots':booking.slots(actor,request.GET.dict())}

@endpoint
def invoice_detail(request,b,pk):
    actor=authenticate(request);i=get('invoice',int(pk));require(i,'结算不存在',404);en=get('encounter',i['encounter_id']);a=get('appointment',en['appointment_id'])
    if actor.role in ('patient','representative'):actor.patient_access(a['patient_id'],'invoices')
    else:actor.allow('reception','dentist','manager','finance','director');actor.clinic_access(a['clinic_id'])
    if actor.role=='dentist':require(a['dentist_id']==actor.employee,'结算超出本人就诊范围',403)
    rev=one("SELECT * FROM invoice_revision WHERE invoice_id=%s AND validity='current'",[i['id']]);require(rev,'尚无有效结算',404)
    clinic=get('clinic',a['clinic_id']);patient=get('patient',a['patient_id']);doctor=get('employee',a['dentist_id'])
    actual=one('SELECT started_at FROM encounter_revision WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
    return dict(i,current_revision=rev,lines=rows('SELECT * FROM invoice_line WHERE invoice_revision_id=%s ORDER BY line_no',[rev['id']]),
      copy_details={'patient_name':patient['full_name'],'clinic_name':clinic['clinic_name'],'clinic_address':clinic['postal_address'],
        'clinic_phone':clinic['phone'],'dentist_name':doctor['full_name'],'encounter_no':en['encounter_no'],'started_at':actual['started_at']})

@endpoint
def encounter_detail(request,b,pk):
    actor=authenticate(request);actor.allow('dentist');en,a=clinical.load_encounter(actor,pk,False)
    return dict(en,appointment=a,phases=rows('SELECT p.* FROM treatment_phase p JOIN appointment_phase ap ON ap.phase_id=p.id WHERE ap.appointment_id=%s',[a['id']]),notes=rows('SELECT * FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC',[en['id']]),treatments=rows('SELECT r.* FROM treatment_revision r JOIN treatment t ON t.id=r.treatment_id WHERE t.encounter_id=%s ORDER BY t.line_no,r.revision_no DESC',[en['id']]),allergies=rows('SELECT ar.*,s.substance_name FROM allergy_revision ar JOIN patient_allergy pa ON pa.id=ar.allergy_id JOIN allergy_substance s ON s.id=pa.substance_id WHERE pa.patient_id=%s ORDER BY ar.id DESC',[a['patient_id']]))

@endpoint
def plan_detail(request,b,pk):
    actor=authenticate(request);actor.allow('dentist');plan=get('treatment_plan',int(pk));require(plan,'计划不存在',404);actor.patient_access(plan['patient_id'])
    rev=one('SELECT * FROM plan_revision WHERE plan_id=%s ORDER BY revision_no DESC LIMIT 1',[plan['id']]);require(rev,'计划尚无修订')
    phases=rows('SELECT p.*,s.* FROM treatment_phase p JOIN phase_specification s ON s.phase_id=p.id WHERE s.plan_revision_id=%s ORDER BY p.phase_no',[rev['id']]);numbers={p['phase_id']:p['phase_no'] for p in phases}
    for p in phases:p['items']=rows('SELECT * FROM phase_item WHERE phase_specification_id=%s ORDER BY id',[p['id']]);p['clinical_released']=p['progress_outcome'] in ('ready','booked','completed')
    deps=rows('SELECT * FROM phase_dependency WHERE plan_revision_id=%s',[rev['id']]);return dict(plan,revision=rev,phases=phases,dependencies=[{'predecessor':numbers[e['predecessor_phase_id']],'successor':numbers[e['successor_phase_id']]} for e in deps])

@endpoint
def report_view(request,b):
    from django.db import transaction
    actor=authenticate(request)
    with transaction.atomic():
        one('SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))',['adc:financial-sources'])
        return finance.calculate(actor,request.GET['quarter_id'],request.GET.get('clinic_id'))[0]

@endpoint
def audit_view(request,b):
    from .auditing import query
    require(request.method=='GET','请使用GET',405)
    return query(authenticate(request),request.GET.dict())

@endpoint
def audit_source(request,b,pk):
    from .audit_source import resolve
    require(request.method=='GET','请使用GET',405)
    return resolve(authenticate(request),pk,CASE_ROLES)

@endpoint
def records(request,b):
    actor=authenticate(request);kind=request.GET['resource'];before=int(request.GET.get('before',2**63-1));q=request.GET.get('q','').strip();require(len(q)<=100,'查询条件过长')
    bounds=[]
    for key in ('from_date','to_date'):
        raw=request.GET.get(key,'')
        if raw:
            try:value=date.fromisoformat(raw)
            except ValueError:require(False,'查询日期须为有效的年-月-日')
            require(raw==value.isoformat() and value.year<9999,'查询日期须为有效的年-月-日（年份小于9999）')
            bounds.append(value)
        else:bounds.append(None)
    require(not all(bounds) or bounds[0]<=bounds[1],'开始日期不能晚于结束日期')
    start=datetime.combine(bounds[0],time.min,ZoneInfo('Asia/Shanghai')) if bounds[0] else None
    finish=datetime.combine(bounds[1]+timedelta(days=1),time.min,ZoneInfo('Asia/Shanghai')) if bounds[1] else None
    personal=actor.role in ('patient','representative');ids=patient_ids(actor) if personal or actor.role=='dentist' else None
    clinic=actor.clinic if actor.scope['scope_kind']!='group' and not personal else None
    if actor.role=='representative':
        require(kind in ('patients','appointments','invoices'),'该数据集使用其业务专用查询',404)
        actor.patient_access(actor.scope['patient_id'],{'patients':'profile','appointments':'booking','invoices':'invoices'}[kind])
    if kind=='patients':
        actor.allow('patient','representative','dentist','reception','manager');where='p.id<%s AND (%s::text=\'\' OR p.full_name ILIKE %s OR p.account_no ILIKE %s OR p.phone=%s)';args=[before,q,'%'+q+'%','%'+q+'%',q]
        if ids is not None:where+=' AND p.id=ANY(%s::bigint[])';args.append(ids)
        elif actor.role=='manager':where+=' AND EXISTS(SELECT 1 FROM appointment a WHERE a.patient_id=p.id AND a.clinic_id=%s)';args.append(clinic)
        data=rows('SELECT p.* FROM patient p WHERE '+where+' ORDER BY p.id DESC LIMIT 200',args)
    elif kind=='appointments':
        actor.allow('patient','representative','dentist','reception','manager');data=rows("SELECT a.*,p.full_name AS patient_name,e.full_name AS dentist_name,c.clinic_name FROM appointment a JOIN patient p ON p.id=a.patient_id JOIN employee e ON e.id=a.dentist_id JOIN clinic c ON c.id=a.clinic_id WHERE a.id<%s AND (%s::bigint IS NULL OR a.clinic_id=%s) AND (%s::boolean=false OR a.patient_id=ANY(%s::bigint[])) AND (%s::bigint IS NULL OR a.dentist_id=%s) AND (%s::timestamptz IS NULL OR a.starts_at>=%s) AND (%s::timestamptz IS NULL OR a.starts_at<%s) AND (%s::text='' OR p.full_name ILIKE %s OR p.account_no ILIKE %s OR a.appointment_no ILIKE %s OR e.full_name ILIKE %s OR c.clinic_name ILIKE %s) ORDER BY a.id DESC LIMIT 200",[before,clinic,clinic,ids is not None,ids or [],actor.employee if actor.role=='dentist' else None,actor.employee if actor.role=='dentist' else None,start,start,finish,finish,q,*['%'+q+'%']*5])
    elif kind=='invoices':
        actor.allow('patient','representative','dentist','reception','manager','finance','director')
        if actor.role=='representative':actor.patient_access(ids[0],'invoices')
        data=rows("SELECT i.*,c.clinic_name,r.id AS revision_id,r.revision_no,r.total_amount,r.issued_at,r.validity FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id AND r.validity='current' JOIN encounter e ON e.id=i.encounter_id JOIN appointment a ON a.id=e.appointment_id JOIN clinic c ON c.id=a.clinic_id JOIN patient p ON p.id=a.patient_id WHERE i.id<%s AND (%s::bigint IS NULL OR a.clinic_id=%s) AND (%s::boolean=false OR a.patient_id=ANY(%s::bigint[])) AND (%s::bigint IS NULL OR a.dentist_id=%s) AND (%s::timestamptz IS NULL OR r.issued_at>=%s) AND (%s::timestamptz IS NULL OR r.issued_at<%s) AND (%s::text='' OR i.invoice_no ILIKE %s) ORDER BY i.id DESC LIMIT 200",[before,clinic,clinic,ids is not None,ids or [],actor.employee if actor.role=='dentist' else None,actor.employee if actor.role=='dentist' else None,start,start,finish,finish,q,'%'+q+'%'])
    else:require(False,'该数据集使用其业务专用查询',404)
    return {'items':data,'next':data[-1]['id'] if len(data)==200 else None,'resource':kind}
