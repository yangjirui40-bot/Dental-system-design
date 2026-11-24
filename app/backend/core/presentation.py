"""Authorised read models for the original use cases; no additional business tables."""
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from .db import rows,one,get
from .http import endpoint
from .security import authenticate,require

# Only explicitly synthetic teaching identities have generated portraits.
# Real staff never inherit a stock identity, biography or clinical credential.
TEACHING_PROFILES={
 'DEMO-DENTIST-001':{'photo':'/static/images/doctor-zhou.jpg','introduction':'注重基础检查和治疗后的复评。需要分阶段完成的治疗，会与你说明每一步的安排、时间和注意事项。'},
 'DEMO-26-DOCTOR-1':{'photo':'/static/images/doctor-xu.jpg','introduction':'接诊时先了解你的就诊诉求、既往治疗和过敏情况。检查后说明可选方案，再与你确认本次治疗。'},
 'DEMO-26-DOCTOR-2':{'photo':'/static/images/doctor-chen.jpg','introduction':'负责日常口腔检查和治疗接续。跨店复诊时，会结合已有记录核对治疗进度，减少重复说明。'}
}

for index, description in enumerate((
    '擅长把初诊检查结果和后续安排讲清楚。',
    '接诊前会核对既往资料，帮助患者了解不同治疗安排。',
    '关注牙周维护及分阶段复评。',
    '负责常规检查、修复评估及复诊安排。',
    '关注访谈、过敏核对和治疗后的观察。',
    '负责修复检查和跨店复诊资料衔接。',
    '注重把阶段方案和实际治疗记录逐项核对。',
    '负责家庭口腔检查与定期维护安排。',
    '接诊时会说明检查步骤、时间及注意事项。',
), 1):
    TEACHING_PROFILES[f'DEMO-NET-D{index:02}'] = {
        'photo': f'/static/images/clinic-network/doctor-{index:02}.jpg',
        'introduction': description,
    }

TEACHING_CLINICS = {
    f'network-clinic-{index:02}@example.invalid': f'/static/images/clinic-network/clinic-{index:02}.jpg'
    for index in range(1, 5)
}


def profile(identity):
    teaching = TEACHING_PROFILES.get(identity['professional_no'], {})
    return {
        'id': identity['id'],
        'full_name': identity['full_name'],
        'photo': teaching.get('photo'),
        'introduction': teaching.get('introduction', '医生简介暂未提供，可联系门店了解。'),
        'synthetic_profile': bool(teaching),
    }


@endpoint
def clinic_directory(request, body):
    require(request.method == 'GET', '请使用GET', 405)
    actor = authenticate(request)
    actor.allow('patient', 'representative')
    if actor.role == 'representative':
        actor.patient_access(actor.scope['patient_id'], 'booking')
    today = timezone.localdate()
    end = today + timedelta(days=14)
    clinics = rows("""SELECT id,clinic_name,postal_address,phone,email FROM clinic
                      WHERE opened_on<=%s AND (closed_on IS NULL OR closed_on>=%s)
                      ORDER BY id""", [today, today])
    shifts = rows("""SELECT d.clinic_id,d.dentist_id,c.work_date,d.starts_at,d.ends_at,
                           e.full_name,p.professional_no
                    FROM practice_duty d
                    JOIN clinic_calendar c ON c.id=d.calendar_id AND c.clinic_id=d.clinic_id AND c.is_open
                    JOIN clinic m ON m.id=d.clinic_id
                    JOIN employee e ON e.id=d.dentist_id JOIN dentist p ON p.id=e.id
                    WHERE d.publication_state='published' AND c.work_date>=%s AND c.work_date<%s
                      AND d.ends_at>%s AND d.starts_at>=c.starts_at AND d.ends_at<=c.ends_at
                      AND m.opened_on<=c.work_date AND (m.closed_on IS NULL OR m.closed_on>=c.work_date)
                      AND e.employed_from<=c.work_date AND (e.employed_to IS NULL OR e.employed_to>=c.work_date)
                    ORDER BY d.starts_at,d.id""", [today, end, timezone.now()])
    teams = {c['id']: {} for c in clinics}
    for shift in shifts:
        if shift['clinic_id'] not in teams:
            continue
        people = teams[shift['clinic_id']]
        if shift['dentist_id'] not in people:
            people[shift['dentist_id']] = dict(
                profile(dict(shift, id=shift['dentist_id'])),
                first_date=shift['work_date'], sessions=[],
            )
        people[shift['dentist_id']]['sessions'].append(
            {key: shift[key] for key in ('work_date','starts_at','ends_at')}
        )
    for clinic in clinics:
        email = clinic.pop('email')
        clinic['photo'] = TEACHING_CLINICS.get(email)
        clinic['synthetic'] = bool(email and email.endswith('@example.invalid'))
        clinic['doctors'] = list(teams[clinic['id']].values())
    return {'clinics': clinics, 'from': today, 'through': end - timedelta(days=1)}


@endpoint
def staff_duty_calendar(request, body):
    require(request.method == 'GET', '请使用GET', 405)
    actor = authenticate(request)
    actor.allow('manager', 'business')
    start = date.fromisoformat(request.GET.get('start', timezone.localdate().isoformat()))
    # Week queries stay bounded and within the Postgres timestamp range.
    require(1900 <= start.year <= 2199, '请检查排班日期', 400)
    end = start + timedelta(days=7)
    clinic_id = int(request.GET.get('clinic_id', 0)) or actor.clinic
    if clinic_id is not None:
        actor.clinic_access(clinic_id)
        require(get('clinic', clinic_id), '门店不存在', 404)
    zone = ZoneInfo('Asia/Shanghai')
    after, before = datetime.combine(start, time.min, zone), datetime.combine(end, time.min, zone)
    doctors = rows("""SELECT p.id,e.full_name,e.employee_no,e.employed_to,p.professional_no
                      FROM dentist p JOIN employee e ON e.id=p.id
                      WHERE (%s::bigint IS NULL OR EXISTS
                        (SELECT 1 FROM practice_duty d WHERE d.dentist_id=p.id AND d.clinic_id=%s))
                      ORDER BY e.full_name,p.id""", [clinic_id, clinic_id])
    duties = rows("""SELECT d.id,d.dentist_id,d.clinic_id,c.clinic_name,d.starts_at,d.ends_at,d.publication_state
                     FROM practice_duty d JOIN clinic c ON c.id=d.clinic_id
                     WHERE (%s::bigint IS NULL OR d.clinic_id=%s)
                       AND d.starts_at<%s AND d.ends_at>%s
                     ORDER BY d.starts_at,c.id,d.id""", [clinic_id, clinic_id, before, after])
    return {
        'doctors': [profile(row) | {k:row[k] for k in ('employee_no','professional_no','employed_to')} for row in doctors],
        'duties': duties, 'start': start, 'end': end,
    }


@endpoint
def staff_calendar_options(request,body,pk):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request)
    actor.allow('business','manager')
    actor.clinic_access(pk)
    today=timezone.localdate()
    return {'calendars':rows("""SELECT * FROM clinic_calendar
      WHERE clinic_id=%s AND is_open AND work_date>=%s AND work_date<%s ORDER BY work_date,session_no""",
      [pk,today,today+timedelta(days=90)])}


@endpoint
def booking_options(request,b):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);actor.allow('patient','representative','reception','manager')
    clinic_id=int(request.GET['clinic_id']);patient_id=request.GET.get('patient_id')
    if actor.role in ('patient','representative'):
        require(patient_id,'请选择获授权就诊人');actor.patient_access(int(patient_id),'booking')
    else:actor.clinic_access(clinic_id)
    if actor.role=='manager':
        original=get('appointment',int(request.GET.get('appointment_id',0)))
        require(original and original['clinic_id']==actor.clinic,'主管仅可按已有预约协助改约',403)
    clinic=get('clinic',clinic_id);require(clinic,'门店不存在',404)
    day=date.fromisoformat(request.GET.get('date',timezone.localdate().isoformat()))
    require(day>=timezone.localdate(),'请选择当日或未来日期')
    start=timezone.make_aware(datetime.combine(day,time.min),ZoneInfo('Asia/Shanghai'));end=start+timedelta(days=1)
    calendars=rows("""SELECT c.id,c.work_date,c.session_no,c.starts_at,c.ends_at,c.is_open,c.exception_reason
      FROM clinic_calendar c WHERE c.clinic_id=%s AND c.work_date BETWEEN %s AND %s ORDER BY c.work_date,c.session_no""",[clinic_id,day,day+timedelta(days=30)])
    duties=rows("""SELECT d.id,d.dentist_id,d.starts_at,d.ends_at,e.full_name FROM practice_duty d JOIN employee e ON e.id=d.dentist_id
      WHERE d.clinic_id=%s AND d.publication_state='published' AND d.starts_at>=%s AND d.starts_at<%s ORDER BY d.starts_at""",[clinic_id,start,start+timedelta(days=31)])
    published_days={d['starts_at'].astimezone(ZoneInfo('Asia/Shanghai')).date() for d in duties}
    days=sorted({c['work_date'] for c in calendars if c['is_open'] and c['work_date'] in published_days})
    standards=rows("""SELECT s.* FROM treatment_standard s JOIN treatment_catalog t ON t.id=s.treatment_id
      WHERE s.approval_state='approved' AND t.is_available AND s.valid_from<%s AND (s.valid_to IS NULL OR s.valid_to>%s)
      ORDER BY s.treatment_id,s.revision_no DESC""",[end,start])
    doctors=[]
    for dentist_id in dict.fromkeys(d['dentist_id'] for d in duties):
        duty=next(d for d in duties if d['dentist_id']==dentist_id)
        qualifications=rows("""SELECT k.qualification_name FROM dentist_qualification q JOIN qualification_kind k ON k.id=q.qualification_kind_id
          WHERE q.dentist_id=%s AND q.verification_result='verified' AND q.revoked_at IS NULL AND q.valid_from<=%s AND (q.valid_to IS NULL OR q.valid_to>=%s) ORDER BY k.id""",[dentist_id,day,day])
        identity=get('dentist',dentist_id)
        public = profile(dict(identity, full_name=duty['full_name']))
        if (identity['professional_no'] or '').startswith('DEMO-NET-D') and request.GET.get('assets') != 'network':
            public['photo'] = None
        doctors.append(public | {
            'professional_no':identity['professional_no'], 'qualifications':[q['qualification_name'] for q in qualifications],
        })
    return {'clinic':{k:clinic[k] for k in ['id','clinic_name','postal_address','phone','email','opened_on','closed_on']},'days':days,'calendars':calendars,'doctors':doctors,'standards':standards,
      'operatories':rows("SELECT id,operatory_name,resource_state FROM operatory WHERE clinic_id=%s ORDER BY id",[clinic_id]),'date':day}

def permitted_appointment(actor,pk):
    a=one("""SELECT a.*,p.full_name AS patient_name,e.full_name AS dentist_name,c.clinic_name,c.postal_address,c.phone AS clinic_phone,o.operatory_name
      FROM appointment a JOIN patient p ON p.id=a.patient_id JOIN employee e ON e.id=a.dentist_id JOIN clinic c ON c.id=a.clinic_id JOIN operatory o ON o.id=a.operatory_id WHERE a.id=%s""",[pk])
    require(a,'预约不存在或不在授权范围',404)
    if actor.role in ('patient','representative'):actor.patient_access(a['patient_id'],'booking')
    else:
        actor.allow('reception','manager','dentist');actor.clinic_access(a['clinic_id'])
        if actor.role=='dentist':require(a['dentist_id']==actor.employee,'预约不在授权范围',403)
    return a

@endpoint
def appointment_detail(request,b,pk):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);a=permitted_appointment(actor,pk)
    events=rows("""SELECT e.id,e.event_kind,e.initiator_kind,e.reason_description,e.occurred_at,e.received_at,u.display_name AS actor_name
      FROM appointment_event e LEFT JOIN user_account u ON u.id=e.acting_account_id WHERE e.appointment_id=%s ORDER BY e.occurred_at,e.id""",[a['id']])
    next_appointment=one('SELECT id,appointment_no,starts_at,resolution FROM appointment WHERE previous_appointment_id=%s AND patient_id=%s',[a['id'],a['patient_id']])
    previous=one('SELECT id,appointment_no,starts_at,resolution FROM appointment WHERE id=%s AND patient_id=%s',[a['previous_appointment_id'],a['patient_id']]) if a['previous_appointment_id'] else None
    encounter=one('SELECT id,encounter_no FROM encounter WHERE appointment_id=%s',[a['id']])
    invoice=one("SELECT i.id,i.invoice_no,r.revision_no,r.total_amount FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id AND r.validity='current' WHERE i.encounter_id=%s",[encounter['id']]) if encounter else None
    phases=rows('SELECT p.id,p.progress_outcome,s.phase_title,s.responsible_clinic_id FROM appointment_phase ap JOIN treatment_phase p ON p.id=ap.phase_id JOIN phase_specification s ON s.id=ap.phase_specification_id WHERE ap.appointment_id=%s ORDER BY p.phase_no',[a['id']])
    return {'appointment':a,'events':events,'requested_items':rows('SELECT treatment_id,request_description FROM appointment_request_item WHERE appointment_id=%s',[a['id']]),'phases':phases,'previous':previous,'next':next_appointment,'encounter':encounter,'invoice':invoice}

@endpoint
def patient_record(request,b,pk):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);actor.allow('patient','representative','reception','dentist')
    # Reception verifies identity before a first appointment; other actors need
    # their existing patient/clinical relationship or explicit profile authority.
    if actor.role!='reception':actor.patient_access(pk,'profile')
    patient=get('patient',pk);require(patient,'患者不存在',404)
    before=int(request.GET.get('history_before',2**63-1))
    def history(kind):
        if kind=='profile':
            items=rows('SELECT r.*,u.display_name AS recorded_name FROM patient_revision r JOIN user_account u ON u.id=r.recorded_account_id WHERE r.patient_id=%s AND r.id<%s ORDER BY r.id DESC LIMIT 50',[pk,before])
        else:
            items=rows('SELECT r.*,s.substance_name,u.display_name AS recorded_name FROM allergy_revision r JOIN patient_allergy a ON a.id=r.allergy_id JOIN allergy_substance s ON s.id=a.substance_id JOIN user_account u ON u.id=r.recorded_account_id WHERE a.patient_id=%s AND r.id<%s ORDER BY r.id DESC LIMIT 50',[pk,before])
        return {'items':items,'next':items[-1]['id'] if len(items)==50 else None}
    kind=request.GET.get('history_kind')
    if kind:
        require(kind in ('profile','allergy'),'请选择基本资料或过敏修订')
        return history(kind)
    allergies=rows("""SELECT a.id,s.substance_name,r.revision_no,r.reaction_description,r.verification_result,r.report_source,r.recorded_at
      FROM patient_allergy a JOIN allergy_substance s ON s.id=a.substance_id
      JOIN LATERAL (SELECT * FROM allergy_revision WHERE allergy_id=a.id ORDER BY revision_no DESC LIMIT 1) r ON true
      WHERE a.patient_id=%s ORDER BY a.id""",[pk])
    return {'patient':patient,'allergies':allergies,'profile_history':history('profile'),'allergy_history':history('allergy'),
      'contacts':rows('SELECT id,full_name,phone,relationship,contact_purpose FROM patient_contact WHERE patient_id=%s ORDER BY id',[pk]),
      'authorities':rows('SELECT id,contact_id,permission_scope,valid_from,valid_to,revoked_at FROM patient_authority WHERE patient_id=%s ORDER BY id DESC',[pk])}

@endpoint
def patient_journey(request,b):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);actor.allow('patient','representative')
    patient_id=int(request.GET['patient_id']);actor.patient_access(patient_id,'booking')
    plans=rows("""SELECT p.id,p.plan_no,r.revision_no,r.confirmed_at,r.id AS revision_id
      FROM treatment_plan p JOIN plan_revision r ON r.plan_id=p.id AND r.confirmation_state='confirmed'
      WHERE p.patient_id=%s ORDER BY p.id DESC""",[patient_id])
    for plan in plans:
        phases=rows("""SELECT p.id,p.phase_no,p.progress_outcome,p.pause_or_end_reason,s.phase_title,s.earliest_at,s.latest_at,
          s.responsible_clinic_id,c.clinic_name,s.estimated_fee,s.id AS specification_id
          FROM treatment_phase p JOIN phase_specification s ON s.phase_id=p.id AND s.plan_revision_id=%s
          JOIN clinic c ON c.id=s.responsible_clinic_id ORDER BY p.phase_no""",[plan['revision_id']])
        for phase in phases:
            phase['predecessors']=rows("""SELECT p.id,s.phase_title,p.progress_outcome FROM phase_dependency d
              JOIN treatment_phase p ON p.id=d.predecessor_phase_id
              JOIN phase_specification s ON s.phase_id=p.id AND s.plan_revision_id=d.plan_revision_id
              WHERE d.plan_revision_id=%s AND d.successor_phase_id=%s ORDER BY p.phase_no""",[plan['revision_id'],phase['id']])
            phase['items']=rows("""SELECT i.standard_id,i.planned_quantity,i.site_description,t.treatment_name,t.duration_minutes
              FROM phase_item i JOIN treatment_standard t ON t.id=i.standard_id WHERE i.phase_specification_id=%s ORDER BY i.id""",[phase['specification_id']])
            phase['appointment']=one("""SELECT a.id,a.appointment_no,a.starts_at,a.ends_at,a.resolution FROM phase_reservation r
              JOIN appointment a ON a.id=r.appointment_id WHERE r.phase_id=%s""",[phase['id']])
            phase['can_book']=phase['progress_outcome']=='ready' and not phase['appointment'] and all(p['progress_outcome']=='completed' for p in phase['predecessors']) and (not phase['latest_at'] or phase['latest_at']>timezone.now())
        plan['phases']=phases;plan.pop('revision_id')
    return {'plans':plans}

@endpoint
def frozen_report(request,b,pk):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);actor.allow('manager','director');report=get('quarter_report',pk);require(report,'报告不存在',404)
    clinic=actor.clinic if actor.scope['scope_kind']!='group' else None
    performance=rows("""SELECT p.*,e.full_name AS dentist_name,c.clinic_name FROM dentist_performance p
      JOIN employee e ON e.id=p.dentist_id JOIN clinic c ON c.id=p.clinic_id
      WHERE p.report_id=%s AND (%s::bigint IS NULL OR p.clinic_id=%s) ORDER BY p.clinic_id,p.dentist_id""",[pk,clinic,clinic])
    require(clinic is None or performance,'报告没有当前授权门店的来源',403)
    invoices=rows("""SELECT i.invoice_no,ir.id AS invoice_revision_id,ir.revision_no,ir.total_amount,er.id AS encounter_revision_id,
      er.started_at,a.clinic_id,a.dentist_id FROM report_invoice_source rs JOIN invoice_revision ir ON ir.id=rs.invoice_revision_id
      JOIN invoice i ON i.id=ir.invoice_id JOIN encounter_revision er ON er.id=rs.encounter_revision_id
      JOIN encounter en ON en.id=er.encounter_id JOIN appointment a ON a.id=en.appointment_id
      WHERE rs.report_id=%s AND (%s::bigint IS NULL OR a.clinic_id=%s) ORDER BY i.id""",[pk,clinic,clinic])
    costs=rows("""SELECT cr.id AS cost_revision_id,cr.revision_no,cs.source_document_no,cs.cost_category,ca.dentist_id,ca.clinic_id,
      ca.allocated_amount,ca.allocation_basis FROM report_cost_source rs JOIN cost_revision cr ON cr.id=rs.cost_revision_id
      JOIN cost_source cs ON cs.id=cr.cost_source_id JOIN cost_allocation ca ON ca.cost_revision_id=cr.id
      WHERE rs.report_id=%s AND ca.quarter_id=%s AND (%s::bigint IS NULL OR ca.clinic_id=%s) ORDER BY cr.id,ca.id""",[pk,report['quarter_id'],clinic,clinic])
    submissions=rows("""SELECT s.id,s.revision_no,s.dentist_id,s.clinic_id,s.supplies_complete,s.operating_complete
      FROM report_submission_source rs JOIN quarter_submission s ON s.id=rs.submission_id WHERE rs.report_id=%s
      AND (%s::bigint IS NULL OR s.clinic_id=%s) ORDER BY s.id""",[pk,clinic,clinic])
    if clinic is not None:
        report={k:v for k,v in report.items() if k not in ('group_net_profit','incentive_fund')}
        report.update(scope_kind='clinic',clinic_id=clinic,net_profit=sum(p['net_profit'] for p in performance))
    else:report['scope_kind']='group'
    return dict(report,quarter=get('fiscal_quarter',report['quarter_id']),rows=performance,sources={'invoices':invoices,'costs':costs,'submissions':submissions},
      source_mode='frozen_financial_versions',operations_included=False)
