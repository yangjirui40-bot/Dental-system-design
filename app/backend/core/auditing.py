"""UC17: scoped audit filters and original before/after version references."""
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from .db import get,one,rows
from .security import require

VERSION_TABLES={
 'UC01':{'save':'patient','allergy':'allergy_revision'},
 'UC03':{'cancel':'appointment','reschedule':'appointment','contact':'followup_contact','assign':'followup_task'},
 'UC04':{'arrive':'appointment','leave':'appointment','no_show':'appointment','correct':'encounter_revision'},
 'UC05':{'draft':'clinical_note','sign':'clinical_note','exception':'clinical_note'},
 'UC07':{'save':'clinic'},'UC08':{'employee':'employee','qualification':'dentist_qualification','revoke':'dentist_qualification'},
 'UC09':{'publish':'practice_duty','replace':'practice_duty','stop':'practice_duty','draft':'practice_duty','publish-draft':'practice_duty'},
 'UC10':{'draft':'treatment_standard','approve':'treatment_standard','reject':'treatment_standard'},
 'UC11':{'source':'cost_revision','review':'cost_allocation','submission':'quarter_submission','review-submission':'quarter_submission'},
 'UC12':{'confirm':'quarter_report'},'UC13':{'phase':'treatment_phase'},
 'UC15':{'calendar':'clinic_calendar','operatory':'operatory'}
}
PREFIX={'invoice_revision':'ir','plan_revision':'pr','patient':'p','appointment':'a','clinic':'c','employee':'e','practice_duty':'d','treatment_standard':'s',
 'clinical_note':'cn','allergy_revision':'ar','encounter_revision':'er','cost_revision':'cr','quarter_submission':'qs',
 'quarter_report':'qr','treatment_phase':'ph','clinic_calendar':'cal','operatory':'op','cost_allocation':'ca','dentist_qualification':'dq','followup_contact':'fc','followup_task':'ft'}

def reference(table,row):
    if not row:return None
    return f"{PREFIX.get(table,table)}:{row['id']}:{row.get('revision_no',row.get('row_version',1))}"[:40]

def before_version(actor,code,body):
    action=body.get('action','save');table=VERSION_TABLES.get(code,{}).get(action)
    pk=body.get('id') or (body.get('draft_id') if code=='UC09' else None)
    if code=='UC01' and action=='save':pk=pk or actor.account.get('patient_id')
    if code=='UC04' and action in ('arrive','leave','no_show'):pk=body.get('appointment_id')
    if code=='UC13' and action=='phase':pk=body.get('phase_id')
    if code=='UC05':
        row=one('SELECT * FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[body.get('encounter_id')])
        return reference('clinical_note',row)
    if code=='UC01' and action=='allergy':
        return reference('allergy_revision',one('SELECT r.* FROM allergy_revision r JOIN patient_allergy a ON a.id=r.allergy_id WHERE a.patient_id=%s AND a.substance_id=%s ORDER BY r.revision_no DESC LIMIT 1',[pk,body.get('substance_id')]))
    if code=='UC11' and action=='source' and body.get('source_id'):
        return reference('cost_revision',one('SELECT * FROM cost_revision WHERE cost_source_id=%s ORDER BY revision_no DESC LIMIT 1',[body['source_id']]))
    if code=='UC04' and action=='correct':
        return reference('encounter_revision',one('SELECT r.* FROM encounter_revision r JOIN encounter e ON e.id=r.encounter_id WHERE e.appointment_id=%s ORDER BY r.revision_no DESC LIMIT 1',[body.get('appointment_id')]))
    if code=='UC06':
        row=one("SELECT r.* FROM invoice_revision r JOIN invoice i ON i.id=r.invoice_id WHERE i.encounter_id=%s AND r.validity='current'",[body.get('encounter_id')])
        return reference('invoice_revision',row)
    if code=='UC13' and action in ('confirm','draft') and pk:
        return reference('plan_revision',one('SELECT * FROM plan_revision WHERE plan_id=%s ORDER BY revision_no DESC LIMIT 1',[pk]))
    if code=='UC12' and action=='confirm':return reference('quarter_report',one('SELECT * FROM quarter_report WHERE quarter_id=%s ORDER BY revision_no DESC LIMIT 1',[body.get('quarter_id')]))
    if table and pk:
        return reference(table,get(table,int(pk)))
    return None

def after_version(code,body,result):
    if result.get('current_revision'):return reference('invoice_revision',result['current_revision'])
    if result.get('revision'):return reference('plan_revision',result['revision'])
    table=VERSION_TABLES.get(code,{}).get(body.get('action','save'))
    return reference(table,result) if table and result.get('id') else None

def query(actor,params):
    actor.allow('manager','director')
    start=params.get('date_from','');end=params.get('date_to','');bounds=[]
    for raw in (start,end):
        try:bounds.append(date.fromisoformat(raw) if raw else None)
        except ValueError:require(False,'请输入有效的起止日期')
    require(not all(bounds) or bounds[1]>=bounds[0],'结束日期不能早于开始日期')
    selected=params.get('clinic_id');clinic=int(selected) if selected else actor.clinic
    if selected:actor.clinic_access(clinic)
    where=['a.id<%s'];args=[int(params.get('before',2**63-1))]
    if clinic is not None:where.append('a.scope_clinic_id=%s');args.append(clinic)
    tz=ZoneInfo('Asia/Shanghai')
    if bounds[0]:where.append('a.occurred_at>=%s');args.append(datetime.combine(bounds[0],time.min,tz))
    if bounds[1]:where.append('a.occurred_at<%s');args.append(datetime.combine(bounds[1]+timedelta(days=1),time.min,tz))
    for field,column in [('account_id','a.account_id'),('business_type','a.object_kind'),('reference','a.business_reference')]:
        if params.get(field):
            value=str(params[field]).strip();require(len(value)<=100,'筛选内容过长')
            if field=='business_type':require(value in [f'UC{i:02}' for i in range(1,18)],'业务类型无效')
            where.append(column+'=%s');args.append(int(value) if field=='account_id' else value)
    if params.get('account'):
        name=params['account'].strip();require(len(name)<=100,'账号筛选过长')
        where.append('(u.login_name ILIKE %s OR u.display_name ILIKE %s)');args.extend(['%'+name+'%']*2)
    if params.get('operation'):
        operation=params['operation'].strip();require(len(operation)<=40,'操作筛选过长');where.append('a.operation_name=%s');args.append(operation)
    outcome=params.get('result','');require(outcome in ('','completed','denied'),'办理结果无效')
    if outcome:where.append("a.operation_name LIKE 'denied.%%'" if outcome=='denied' else "a.operation_name NOT LIKE 'denied.%%'")
    items=rows("""SELECT a.*,u.login_name,u.display_name,r.role_name,c.clinic_name,
      CASE WHEN a.operation_name LIKE 'denied.%%' THEN 'denied' ELSE 'completed' END AS result
      FROM audit_event a LEFT JOIN user_account u ON u.id=a.account_id LEFT JOIN access_role r ON r.id=a.acting_role_id
      LEFT JOIN clinic c ON c.id=a.scope_clinic_id WHERE """+' AND '.join(where)+' ORDER BY a.id DESC LIMIT 100',args)
    return {'items':items,'next':items[-1]['id'] if len(items)==100 else None,'filters':{k:params[k] for k in ['date_from','date_to','account','business_type','reference','operation','result'] if params.get(k)}}
