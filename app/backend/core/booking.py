"""UC02/03/04/09: calendar, skills, three resources and stable phase identity."""
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import uuid
from django.db import transaction
from django.utils import timezone
from .db import rows, one, get, insert, update, execute, business_no
from .security import require
from .rules import timestamp, version
ACTIVE=('booked','arrived','seen')

def qualifications(dentist, start, end, required):
    return all(one("SELECT id FROM dentist_qualification WHERE dentist_id=%s AND qualification_kind_id=%s AND verification_result='verified' AND revoked_at IS NULL AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s)",[dentist,q,start.date(),(end-timedelta(microseconds=1)).date()]) for q in required)

def validate(actor, b, exclude=None, lock=False):
    start,end=timestamp(b['starts_at']),timestamp(b['ends_at'])
    require(end>start and start>=timezone.now(),'请选择未来完整有效时段')
    patient=int(b.get('patient_id') or actor.account['patient_id']);dentist=int(b['dentist_id']);clinic=int(b['clinic_id']);duty_id=int(b['duty_id']);operatory=int(b['operatory_id'])
    require(get('patient',patient),'患者不存在',404)
    if actor.role in ('patient','representative'):actor.patient_access(patient,'booking')
    else: actor.clinic_access(clinic)
    if lock:
        # Lock identities in a stable order before conflict reads; exclusion
        # constraints remain the final guard when requests race.
        for prefix,num in [('patient',patient),('dentist',dentist),('operatory',operatory)]:one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',[f'{prefix}:{num}'])
    duty=get('practice_duty',duty_id,lock);require(duty and duty['dentist_id']==dentist and duty['clinic_id']==clinic and duty['publication_state']=='published','所选出诊尚未发布或已经失效')
    require(duty['starts_at']<=start and duty['ends_at']>=end,'预约必须完整落在医生出诊时段')
    calendar=get('clinic_calendar',duty['calendar_id'],lock);require(calendar and calendar['clinic_id']==clinic and calendar['is_open'] and calendar['starts_at']<=start and end<=calendar['ends_at'],'预约不在门店营业时段')
    c=get('clinic',clinic,lock);require(c and c['opened_on']<=start.date() and (not c['closed_on'] or start.date()<=c['closed_on']),'门店未营业或已经停用')
    emp=get('employee',dentist);require(emp and emp['employed_from']<=start.date() and (not emp['employed_to'] or end.date()<=emp['employed_to']),'牙医不在有效任职期间')
    op=get('operatory',operatory,lock);require(op and op['clinic_id']==clinic and op['resource_state']=='active','诊疗位不可用或门店不符')
    required={r['qualification_kind_id'] for r in rows('SELECT qualification_kind_id FROM duty_skill WHERE duty_id=%s',[duty_id])}
    # The saved phase supplies its own projects and quantities. The caller cannot
    # omit a planned skill or shorten the reserved duration by sending fewer IDs.
    planned=[];phase_id=b.get('phase_id')
    if phase_id:
        candidate=get('treatment_phase',int(phase_id));require(candidate,'阶段不存在')
        plan=get('treatment_plan',candidate['plan_id'],lock);require(plan and plan['patient_id']==patient,'阶段属于其他患者',403)
        phase=get('treatment_phase',int(phase_id),lock);require(phase['progress_outcome'] in ('ready','booked'),'阶段尚未获准可约')
        specification=one("SELECT s.id FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id AND r.confirmation_state='confirmed' WHERE s.phase_id=%s",[phase_id]);require(specification,'阶段没有已确认定义')
        planned=rows('SELECT standard_id,planned_quantity FROM phase_item WHERE phase_specification_id=%s',[specification['id']])
        require(all(item['planned_quantity'].is_finite() and item['planned_quantity']>0 for item in planned),'阶段预计数量需由牙医核实')
    standards=[]
    standard_ids=sorted({int(sid) for sid in b.get('standard_ids',[])}|{item['standard_id'] for item in planned})
    for sid in standard_ids:
        s=get('treatment_standard',int(sid));require(s and s['approval_state']=='approved' and s['valid_from']<=start and (not s['valid_to'] or s['valid_to']>=end),'项目标准尚未获准或在该时点失效')
        require(get('treatment_catalog',s['treatment_id'])['is_available'],'治疗项目已停用');standards.append(s)
        required|={r['qualification_kind_id'] for r in rows('SELECT qualification_kind_id FROM standard_qualification WHERE standard_id=%s',[sid])}
    require(standards or str(b.get('presenting_request','')).strip() or phase_id,'请选择项目、填写就诊诉求或接续已确认阶段')
    quantities={}
    for item in planned:quantities[item['standard_id']]=quantities.get(item['standard_id'],Decimal(0))+item['planned_quantity']
    minimum=sum(Decimal(s['duration_minutes'])*quantities.get(s['id'],Decimal(1)) for s in standards) if standards else Decimal(30)
    require((end-start).total_seconds()>=minimum*60,'完整时段不足以安排所选项目及已确认方案的预计数量')
    require(qualifications(dentist,start,end,required),'医生资质未覆盖所需项目或就诊时点')
    conflict=one("SELECT id FROM appointment WHERE resolution IN ('booked','arrived','seen') AND starts_at<%s AND ends_at>%s AND (dentist_id=%s OR patient_id=%s OR operatory_id=%s) AND (%s::bigint IS NULL OR id<>%s)",[end,start,dentist,patient,operatory,exclude,exclude])
    require(not conflict,'医生、患者或诊疗位的完整时段已占用',409)
    phase_id=b.get('phase_id')
    if phase_id:
        phase=get('treatment_phase',int(phase_id),lock);require(phase and phase['progress_outcome'] in ('ready','booked'),'阶段尚未获准可约')
        plan=get('treatment_plan',phase['plan_id']);require(plan['patient_id']==patient,'阶段属于其他患者')
        spec=one("SELECT s.* FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id WHERE s.phase_id=%s AND r.confirmation_state='confirmed'",[phase_id]);require(spec,'阶段没有已确认定义')
        require(spec['responsible_clinic_id']==clinic,'当前阶段承接门店不符')
        require((not spec['earliest_at'] or start>=spec['earliest_at']) and (not spec['latest_at'] or end<=spec['latest_at']),'时间不在阶段可约期间')
        blocked=one("SELECT d.predecessor_phase_id FROM phase_dependency d JOIN treatment_phase p ON p.id=d.predecessor_phase_id WHERE d.plan_revision_id=%s AND d.successor_phase_id=%s AND p.progress_outcome<>'completed'",[spec['plan_revision_id'],phase_id]);require(not blocked,'前序阶段尚未完成')
        stage_skills={r['qualification_kind_id'] for r in rows('SELECT DISTINCT q.qualification_kind_id FROM phase_item i JOIN standard_qualification q ON q.standard_id=i.standard_id WHERE i.phase_specification_id=%s',[spec['id']])}
        require(qualifications(dentist,start,end,stage_skills),'牙医资质未覆盖该阶段的计划治疗项目')
        reserved=one('SELECT * FROM phase_reservation WHERE phase_id=%s',[phase_id]);require(not reserved or reserved['appointment_id']==exclude,'阶段已有有效预约',409)
    return dict(patient_id=patient,dentist_id=dentist,clinic_id=clinic,duty_id=duty_id,operatory_id=operatory,starts_at=start,ends_at=end),standards

def book(actor,b,exclude=None):
    data,standards=validate(actor,b,exclude,True)
    description=b.get('presenting_request','')
    if not str(description).strip() and b.get('phase_id'):
        source=one("SELECT s.phase_title FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id AND r.confirmation_state='confirmed' WHERE s.phase_id=%s",[b['phase_id']]);description='接续已确认阶段：'+source['phase_title']
    a=insert('appointment',dict(**data,appointment_no=business_no('A'),resolution='booked',presenting_request=description,special_needs=b.get('special_needs',''),created_by=actor.employee,created_at=timezone.now(),row_version=1,request_channel='patient_portal' if actor.role=='patient' else 'representative_portal' if actor.role=='representative' else 'reception',created_account_id=actor.id,previous_appointment_id=exclude))
    for s in standards:insert('appointment_request_item',dict(appointment_id=a['id'],treatment_id=s['treatment_id'],request_description=s['treatment_name']))
    if b.get('phase_id'):
        phase=int(b['phase_id']);spec=one("SELECT s.* FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id WHERE s.phase_id=%s AND r.confirmation_state='confirmed'",[phase]);insert('appointment_phase',dict(appointment_id=a['id'],phase_id=phase,phase_specification_id=spec['id']));insert('phase_reservation',dict(phase_id=phase,appointment_id=a['id'],reserved_at=timezone.now()));p=get('treatment_phase',phase);update('treatment_phase',phase,dict(progress_outcome='booked',row_version=p['row_version']+1));execute('UPDATE followup_task SET closed_at=clock_timestamp(),closing_reason=%s WHERE phase_id=%s AND closed_at IS NULL',['已通过有效预约接续',phase])
    return a

def event(actor,a,kind,reason='',request_id=None,original_duty_id=None,replacement_duty_id=None,initiator_kind=None):
    now=timezone.now()
    return insert('appointment_event',dict(appointment_id=a['id'],original_duty_id=original_duty_id,replacement_duty_id=replacement_duty_id,event_kind=kind,initiator_kind=initiator_kind or ('patient' if actor.role in ('patient','representative') else 'organisation'),reason_code=kind,reason_description=reason,occurred_at=now,received_at=now,decided_at=now,completed_at=now,performed_by=actor.employee,request_id=request_id or uuid.uuid4(),acting_account_id=actor.id,request_channel='patient_portal' if actor.role=='patient' else 'representative_portal' if actor.role=='representative' else 'clinic_manager' if actor.role in ('manager','business') else 'reception'))

def followup(actor,a,only_phase=None):
    phases=rows('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s AND (%s::bigint IS NULL OR phase_id=%s)',[a['id'],only_phase,only_phase])
    execute('DELETE FROM phase_reservation WHERE appointment_id=%s AND (%s::bigint IS NULL OR phase_id=%s)',[a['id'],only_phase,only_phase])
    for row in phases:
        phase=get('treatment_phase',row['phase_id'],True)
        if phase['progress_outcome'] in ('completed','terminated','paused'):continue
        update('treatment_phase',phase['id'],dict(progress_outcome='ready',row_version=phase['row_version']+1))
        if not one('SELECT id FROM followup_task WHERE phase_id=%s AND closed_at IS NULL',[phase['id']]):insert('followup_task',dict(patient_id=a['patient_id'],phase_id=phase['id'],source_appointment_id=a['id'],responsible_clinic_id=a['clinic_id'],contact_progress='self_service',next_contact_at=timezone.now()+timedelta(days=2),opened_at=timezone.now(),row_version=1))
    if not phases and get('appointment',a['id'])['resolution']=='unfulfilled' and not one('SELECT id FROM followup_task WHERE source_appointment_id=%s AND phase_id IS NULL AND closed_at IS NULL',[a['id']]):
        insert('followup_task',dict(patient_id=a['patient_id'],source_appointment_id=a['id'],responsible_clinic_id=a['clinic_id'],contact_progress='self_service',next_contact_at=timezone.now()+timedelta(days=2),opened_at=timezone.now(),row_version=1))

def change(actor,b):
    if b['action']=='assign':
        actor.allow('manager');task=get('followup_task',int(b['id']),True);require(task and not task['closed_at'],'待约事项不存在或已经办结');actor.clinic_access(task['responsible_clinic_id']);version(task,b)
        successor=get('employee',int(b['responsible_employee_id']));require(successor and successor['employed_from']<=timezone.localdate() and (not successor['employed_to'] or successor['employed_to']>=timezone.localdate()),'接手职员不在有效任职期')
        require(one("SELECT s.id FROM user_account u JOIN account_scope s ON s.account_id=u.id JOIN access_role r ON r.id=s.role_id WHERE u.employee_id=%s AND u.is_enabled AND s.revoked_at IS NULL AND r.role_code IN ('reception','manager') AND (s.scope_kind='group' OR s.clinic_id=%s)",[successor['id'],task['responsible_clinic_id']]),'接手职员没有本门店当前有效的接续办理岗位')
        deadline=timestamp(b['next_contact_at']);require(deadline>timezone.now() and str(b.get('reason','')).strip(),'请明确接手原因及未来联系期限')
        result=update('followup_task',task['id'],dict(responsible_employee_id=successor['id'],next_contact_at=deadline,row_version=task['row_version']+1))
        insert('followup_contact',dict(task_id=task['id'],contacted_at=timezone.now(),contact_result='needs_assistance',summary='责任交接：'+b['reason'],next_contact_at=deadline,performed_by=actor.employee))
        return result
    if b['action']=='contact':
        actor.allow('reception','manager');task=get('followup_task',int(b['id']),True);require(task and not task['closed_at'],'待约事项不存在或已经办结');actor.clinic_access(task['responsible_clinic_id'])
        require(b.get('summary'),'请填写实际联系结果')
        c=insert('followup_contact',dict(task_id=task['id'],contacted_at=timezone.now(),contact_id=int(b['contact_id']) if b.get('contact_id') else None,contact_result=b['contact_result'],summary=b['summary'],next_contact_at=timestamp(b['next_contact_at']) if b.get('next_contact_at') else None,performed_by=actor.employee))
        update('followup_task',task['id'],dict(contact_progress=b['contact_result'],responsible_employee_id=actor.employee,next_contact_at=c['next_contact_at'],row_version=task['row_version']+1));return c
    require(b['action'] in ('cancel','reschedule'),'未知预约变更操作')
    a=get('appointment',int(b['id']),True);version(a,b)
    if actor.role in ('patient','representative'):actor.patient_access(a['patient_id'],'booking')
    else:actor.clinic_access(a['clinic_id'])
    require(a['resolution'] in ('booked','arrived','unfulfilled'),'当前预约状态不允许取消或改期')
    require(str(b.get('reason','')).strip(),'请填写变更原因')
    update('appointment',a['id'],dict(resolution='rescheduled' if b['action']=='reschedule' else 'cancelled',row_version=a['row_version']+1))
    followup(actor,a)
    if b['action']=='reschedule':
        target=dict(b['replacement']);target['patient_id']=a['patient_id'];phases=rows('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s',[a['id']]);require(len(phases)<=1,'多阶段改期须逐阶段核实')
        if phases:target['phase_id']=phases[0]['phase_id']
        result=book(actor,target,a['id'])
    else:result=get('appointment',a['id'])
    initiator='organisation' if a['resolution']=='unfulfilled' else 'patient' if actor.role in ('patient','representative') else b.get('initiator_kind','patient')
    require(initiator in ('patient','organisation'),'请选择真实的变更发起方')
    execute('UPDATE followup_task SET closed_at=clock_timestamp(),closing_reason=%s WHERE source_appointment_id=%s AND phase_id IS NULL AND closed_at IS NULL',['已通过新约接续' if b['action']=='reschedule' else '患者已明确不再保留本次安排',a['id']])
    event(actor,a,b['action'],b['reason'],initiator_kind=initiator);return result

def encounter_action(actor,b):
    a=get('appointment',int(b['appointment_id']),True);require(a,'预约不存在',404)
    action=b['action']
    if actor.role=='patient':actor.patient_access(a['patient_id']);require(action in ('arrive','leave'),'患者仅可报到或登记未接诊离开',403)
    else: actor.clinic_access(a['clinic_id'])
    if action=='arrive':
        require(a['starts_at'].astimezone(ZoneInfo('Asia/Shanghai')).date()==timezone.localdate(),'仅允许办理当日预约报到')
        require(a['resolution'] in ('booked','arrived'),'预约状态不可报到')
        if a['resolution']=='booked':update('appointment',a['id'],dict(resolution='arrived',row_version=a['row_version']+1));event(actor,a,'arrive')
        return get('appointment',a['id'])
    if action=='start':
        actor.allow('dentist');require(a['dentist_id']==actor.employee,'只能确认本人实际接诊',403)
        existing=one('SELECT * FROM encounter WHERE appointment_id=%s',[a['id']])
        if existing:return existing
        require(a['resolution']=='arrived','须先核实到店，再确认实际接诊')
        require(b.get('identity_confirmed') and b.get('allergy_confirmed'),'请核实实际患者身份及过敏情况')
        en=insert('encounter',dict(encounter_no=business_no('E'),appointment_id=a['id']));arrival=one("SELECT occurred_at FROM appointment_event WHERE appointment_id=%s AND event_kind='arrive' ORDER BY id DESC LIMIT 1",[a['id']]);insert('encounter_revision',dict(encounter_id=en['id'],revision_no=1,arrived_at=arrival['occurred_at'] if arrival else None,started_at=timezone.now(),confirmed_by=actor.employee,recorded_at=timezone.now()));update('appointment',a['id'],dict(resolution='seen',row_version=a['row_version']+1));event(actor,a,'start');return en
    require(action in ('no_show','leave','correct'),'未知接诊操作')
    if action=='correct':
        actor.allow('dentist');require(a['dentist_id']==actor.employee,'只能补正本人接诊',403);en=one('SELECT * FROM encounter WHERE appointment_id=%s',[a['id']]);require(en,'无实际接诊记录')
        old=one('SELECT * FROM encounter_revision WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']]);require(b.get('reason'),'请填写补正依据')
        start=timestamp(b['started_at']);arrival=timestamp(b['arrived_at']) if b.get('arrived_at') else old['arrived_at'];end=timestamp(b['ended_at']) if b.get('ended_at') else old['ended_at']
        now=timezone.now();require(start<=now and (end is None or start<=end<=now) and (arrival is None or arrival<=start),'补正须填写真实且顺序一致的已发生时点')
        row=insert('encounter_revision',dict(encounter_id=en['id'],revision_no=old['revision_no']+1,replaces_id=old['id'],arrived_at=arrival,started_at=start,ended_at=end,confirmed_by=actor.employee,recorded_at=now,correction_reason=b['reason']))
        execute("""UPDATE quarter_report SET confirmation_state='stale' WHERE confirmation_state='confirmed' AND
          (id IN (SELECT s.report_id FROM report_invoice_source s JOIN encounter_revision er ON er.id=s.encounter_revision_id WHERE er.encounter_id=%s)
          OR quarter_id IN (SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s))""",[en['id'],start.astimezone(ZoneInfo('Asia/Shanghai')).date(),start.astimezone(ZoneInfo('Asia/Shanghai')).date()])
        return row
    require(a['resolution'] in ('booked','arrived'),'当前状态不可登记未接诊结果');require(b.get('reason'),'须核实并填写事实依据')
    if action=='no_show':actor.allow('reception');require(a['ends_at']<timezone.now(),'尚未到期不能核实未到')
    else:require(a['resolution']=='arrived','尚未报到不能登记到店离开')
    update('appointment',a['id'],dict(resolution='no_show' if action=='no_show' else 'left_unseen',row_version=a['row_version']+1));followup(actor,a);event(actor,a,action,b['reason']);return get('appointment',a['id'])

def slots(actor,q):
    date=q['date'];clinic=int(q['clinic_id']);duration=int(q.get('minutes',30));require(5<=duration<=480,'时长超出可安排范围')
    output=[]
    for duty in rows("SELECT * FROM practice_duty WHERE clinic_id=%s AND publication_state='published' AND (starts_at AT TIME ZONE 'Asia/Shanghai')::date=%s ORDER BY starts_at",[clinic,date]):
        for op in rows("SELECT id FROM operatory WHERE clinic_id=%s AND resource_state='active'",[clinic]):
            start=duty['starts_at']
            while start+timedelta(minutes=duration)<=duty['ends_at']:
                target=dict(q,clinic_id=clinic,patient_id=q.get('patient_id') or actor.account['patient_id'],dentist_id=duty['dentist_id'],duty_id=duty['id'],operatory_id=op['id'],starts_at=start,ends_at=start+timedelta(minutes=duration),standard_ids=[int(x) for x in q.get('standard_ids','').split(',') if x],presenting_request=q.get('presenting_request','初步检查'))
                try:
                    data,_=validate(actor,target,exclude=int(q['appointment_id']) if q.get('appointment_id') else None);output.append(data)
                except Exception as e:
                    from .security import BusinessError
                    if not isinstance(e,BusinessError):raise
                start+=timedelta(minutes=15)
    return output[:240]
