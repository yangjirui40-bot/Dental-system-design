"""UC08/UC15 real unavailability: prevent new booking, preserve clinical truth."""
from django.utils import timezone
from .db import get,rows,one,insert,update,execute
from .security import require,authenticate
from .rules import version,timestamp
from .http import endpoint

def mark_unavailable(actor,appointments,kind,reason):
    from .booking import followup,event
    changed=[]
    for original in appointments:
        a=get('appointment',original['id'],True)
        if a['resolution'] not in ('booked','arrived'):continue
        update('appointment',a['id'],dict(resolution='unfulfilled',row_version=a['row_version']+1))
        followup(actor,a);event(actor,a,kind,reason,initiator_kind='organisation');changed.append(a['id'])
    return changed

def impact(actor,kind,pk):
    actor.allow('manager','business');require(kind in ('calendar','operatory'),'资源类型无效')
    record=get('clinic_calendar' if kind=='calendar' else 'operatory',int(pk));require(record,'资源不存在',404);actor.clinic_access(record['clinic_id'])
    predicate='d.calendar_id=%s' if kind=='calendar' else 'a.operatory_id=%s'
    appointments=rows("""SELECT a.id,a.appointment_no,a.resolution,a.starts_at,a.ends_at,a.dentist_id,a.clinic_id,
      e.full_name AS dentist_name FROM appointment a JOIN practice_duty d ON d.id=a.duty_id
      JOIN employee e ON e.id=a.dentist_id WHERE """+predicate+" AND a.resolution IN ('booked','arrived','seen') AND a.ends_at>%s ORDER BY a.starts_at",[pk,timezone.now()])
    return {'resource':record,'appointments':appointments,'requires_coordination':any(a['resolution'] in ('booked','arrived') for a in appointments),
      'ongoing_encounters_preserved':sum(a['resolution']=='seen' for a in appointments)}

@endpoint
def resource_impact(request,body):
    require(request.method=='GET','请使用GET',405)
    return impact(authenticate(request),request.GET['kind'],int(request.GET['id']))

def resources_action(actor,b):
    actor.allow('manager','business');clinic=int(b['clinic_id']);actor.clinic_access(clinic);now=timezone.now();action=b['action']
    require(action in ('calendar','operatory'),'资源操作无效')
    old=get('clinic_calendar' if action=='calendar' else 'operatory',int(b['id']),True) if b.get('id') else None
    if old:version(old,b);require(old['clinic_id']==clinic,'资源不属于该门店')
    emergency=b.get('change_mode')=='immediate'
    if emergency:require(b.get('impact_acknowledged') is True and str(b.get('unavailable_reason','')).strip(),'实际停业或维修须确认影响责任并填写真实原因')
    affected=[]
    if action=='calendar':
        if old:
            duties=rows("SELECT * FROM practice_duty WHERE calendar_id=%s AND publication_state='published' ORDER BY id FOR UPDATE",[old['id']])
            require(not duties or (emergency and not b['is_open']),'有已发布出诊，须先处理影响；真实临时停业可选择立即阻止新预约并接续原约',409)
            if emergency and not b['is_open']:
                affected=rows("""SELECT a.* FROM appointment a JOIN practice_duty d ON d.id=a.duty_id
                  WHERE d.calendar_id=%s AND a.resolution IN ('booked','arrived') AND a.ends_at>%s ORDER BY a.id FOR UPDATE OF a""",[old['id'],now])
                for d in duties:update('practice_duty',d['id'],dict(publication_state='stopped',stopped_at=now,stop_reason=b['unavailable_reason'],row_version=d['row_version']+1))
        data=dict(clinic_id=clinic,work_date=b['work_date'],session_no=int(b.get('session_no',1)),is_open=b['is_open'],
          starts_at=timestamp(b['starts_at']) if b['is_open'] else None,ends_at=timestamp(b['ends_at']) if b['is_open'] else None,
          exception_reason=b.get('unavailable_reason') if emergency else b.get('exception_reason'),confirmed_by=actor.employee,confirmed_at=now,row_version=old['row_version']+1 if old else 1)
        result=update('clinic_calendar',old['id'],data) if old else insert('clinic_calendar',data)
    else:
        state=b['resource_state'];require(state in ('active','maintenance','inactive'),'资源状态无效')
        if old and state!='active':
            affected=rows("SELECT * FROM appointment WHERE operatory_id=%s AND resolution IN ('booked','arrived') AND ends_at>%s ORDER BY id FOR UPDATE",[old['id'],now])
            require(not affected or emergency,'停用或维修前须处理预约影响；真实故障可选择立即阻止新预约并保留接续责任',409)
        data=dict(clinic_id=clinic,operatory_code=b['operatory_code'],operatory_name=b['operatory_name'],resource_state=state,
          changed_by=actor.employee,changed_at=now,row_version=old['row_version']+1 if old else 1)
        result=update('operatory',old['id'],data) if old else insert('operatory',data)
    changed=mark_unavailable(actor,affected,'calendar_stop' if action=='calendar' else 'resource_stop',b.get('unavailable_reason','')) if emergency else []
    return dict(result,affected_appointment_ids=changed,clinical_encounters_preserved=True)

def revoke_qualification(actor,b):
    from .booking import qualifications
    actor.allow('business');q=get('dentist_qualification',int(b['id']),True);require(q and b.get('reason'),'撤销须填写核实依据')
    one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',[f"dentist:{q['dentist_id']}"])
    require(not q['revoked_at'],'资格已经撤销')
    now=timezone.now();result=update('dentist_qualification',q['id'],dict(revoked_at=now,revocation_reason=b['reason']))
    duties=rows("SELECT * FROM practice_duty WHERE dentist_id=%s AND publication_state='published' AND ends_at>%s ORDER BY id FOR UPDATE",[q['dentist_id'],now]);stopped=[]
    for d in duties:
        skills={x['qualification_kind_id'] for x in rows('SELECT qualification_kind_id FROM duty_skill WHERE duty_id=%s',[d['id']])}
        if not qualifications(q['dentist_id'],d['starts_at'],d['ends_at'],skills):
            update('practice_duty',d['id'],dict(publication_state='stopped',stopped_at=now,stop_reason='所需资格已失效：'+b['reason'],row_version=d['row_version']+1));stopped.append(d['id'])
    appointments=rows("SELECT * FROM appointment WHERE dentist_id=%s AND resolution IN ('booked','arrived') AND ends_at>%s ORDER BY id FOR UPDATE",[q['dentist_id'],now]);invalid=[]
    for a in appointments:
        skills={x['qualification_kind_id'] for x in rows('SELECT qualification_kind_id FROM duty_skill WHERE duty_id=%s',[a['duty_id']])}
        skills.update(x['qualification_kind_id'] for x in rows("""SELECT DISTINCT sq.qualification_kind_id FROM appointment_request_item r
          JOIN treatment_standard s ON s.treatment_id=r.treatment_id AND s.approval_state IN ('approved','retired') AND s.valid_from<=%s AND (s.valid_to IS NULL OR s.valid_to>=%s)
          JOIN standard_qualification sq ON sq.standard_id=s.id WHERE r.appointment_id=%s""",[a['starts_at'],a['ends_at'],a['id']]))
        if a['duty_id'] in stopped or not qualifications(q['dentist_id'],a['starts_at'],a['ends_at'],skills):invalid.append(a)
    changed=mark_unavailable(actor,invalid,'qualification_stop','出诊资格状态变化，原安排无法履行；'+b['reason'])
    return dict(result,affected_appointment_ids=changed,stopped_duty_ids=stopped,clinical_facts_preserved=True)
