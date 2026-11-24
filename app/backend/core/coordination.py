"""UC09 coordination drafts, affected patients and atomic promise-preserving release."""
from django.utils import timezone
from .db import get,rows,insert,update,execute
from .security import require,BusinessError,authenticate
from .rules import timestamp,version
from .http import endpoint

def affected(actor,original):
    data=rows("""SELECT a.*,p.full_name AS patient_name,e.full_name AS dentist_name,c.clinic_name,o.operatory_name
      FROM appointment a JOIN patient p ON p.id=a.patient_id JOIN employee e ON e.id=a.dentist_id
      JOIN clinic c ON c.id=a.clinic_id JOIN operatory o ON o.id=a.operatory_id
      WHERE a.duty_id=%s AND a.resolution IN ('booked','arrived') ORDER BY a.starts_at,a.id""",[original['id']])
    for a in data:
        if actor.role=='business':a['patient_name']='已登记患者'
        a['phase_ids']=[r['phase_id'] for r in rows('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s',[a['id']])]
        a['requested_items']=rows('SELECT treatment_id,request_description FROM appointment_request_item WHERE appointment_id=%s ORDER BY id',[a['id']])
    return data

def preview(actor,body):
    from .administration import validate_duty
    actor.allow('manager','business');original=get('practice_duty',int(body['original_id'])) if body.get('original_id') else None
    if original:actor.clinic_access(original['clinic_id'])
    proposal={k:body[k] for k in ['clinic_id','dentist_id','calendar_id','starts_at','ends_at']}
    proposal['qualification_kind_ids']=body.get('qualification_kind_ids',[])
    issues=[]
    try:validate_duty(actor,proposal,exclude=original['id'] if original and original['publication_state']=='published' else None)
    except BusinessError as e:issues.append(e.message)
    impacted=affected(actor,original) if original else []
    start,end=timestamp(proposal['starts_at']),timestamp(proposal['ends_at'])
    for a in impacted:
        a['agreement_required']=not(int(proposal['dentist_id'])==a['dentist_id'] and int(proposal['clinic_id'])==a['clinic_id'] and start<=a['starts_at'] and a['ends_at']<=end)
        a['suggested_standard_ids']=[]
        for item in a['requested_items']:
            if item['treatment_id']:
                found=rows("SELECT id FROM treatment_standard WHERE treatment_id=%s AND approval_state='approved' AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s) ORDER BY revision_no DESC LIMIT 1",[item['treatment_id'],max(start,a['starts_at']),min(end,max(start,a['starts_at'])+(a['ends_at']-a['starts_at']))])
                if found:a['suggested_standard_ids'].append(found[0]['id'])
    return {'original':original,'proposal':proposal,'affected':impacted,'issues':issues,'can_publish':not issues,
      'agreement_count':sum(a['agreement_required'] for a in impacted),'unchanged_count':sum(not a['agreement_required'] for a in impacted)}

@endpoint
def duty_preview(request,body):
    require(request.method=='POST','请使用POST',405)
    return preview(authenticate(request),body)

@endpoint
def duty_detail(request,body,pk):
    require(request.method=='GET','请使用GET',405);actor=authenticate(request);actor.allow('manager','business')
    duty=get('practice_duty',pk);require(duty,'出诊不存在',404);actor.clinic_access(duty['clinic_id'])
    return dict(duty,qualification_kind_ids=[r['qualification_kind_id'] for r in rows('SELECT qualification_kind_id FROM duty_skill WHERE duty_id=%s',[pk])],affected=affected(actor,duty))

def save_draft(actor,body):
    actor.allow('manager','business');clinic=int(body['clinic_id']);actor.clinic_access(clinic)
    dentist=int(body['dentist_id']);calendar=int(body['calendar_id']);start,end=timestamp(body['starts_at']),timestamp(body['ends_at'])
    require(get('dentist',dentist) and get('clinic',clinic),'门店或牙医不存在')
    cal=get('clinic_calendar',calendar);require(cal and cal['clinic_id']==clinic,'营业日历与门店不符')
    require(end>start,'出诊结束必须晚于开始')
    original=get('practice_duty',int(body['original_id'])) if body.get('original_id') else None
    if original:actor.clinic_access(original['clinic_id'])
    draft=get('practice_duty',int(body['draft_id']),True) if body.get('draft_id') else None
    if draft:
        version(draft,body);actor.clinic_access(draft['clinic_id']);require(draft['publication_state'] in ('draft','pending_coordination'),'仅未发布协调稿可以编辑')
    data=dict(clinic_id=clinic,dentist_id=dentist,calendar_id=calendar,starts_at=start,ends_at=end,replaces_duty_id=original['id'] if original else None,
      publication_state='pending_coordination' if original else 'draft',row_version=draft['row_version']+1 if draft else 1)
    draft=update('practice_duty',draft['id'],data) if draft else insert('practice_duty',data)
    execute('DELETE FROM duty_skill WHERE duty_id=%s',[draft['id']])
    for key in sorted(set(map(int,body.get('qualification_kind_ids',[])))):
        require(get('qualification_kind',key),'资格类别不存在');insert('duty_skill',dict(duty_id=draft['id'],qualification_kind_id=key))
    return dict(draft,original_preserved=True)

def publish_draft(actor,body):
    from .administration import duty_action
    draft=get('practice_duty',int(body['draft_id']),True);require(draft,'协调稿不存在',404);version(draft,body)
    actor.clinic_access(draft['clinic_id']);require(draft['publication_state'] in ('draft','pending_coordination'),'协调稿已经发布或失效')
    proposal={k:draft[k] for k in ['clinic_id','dentist_id','calendar_id','starts_at','ends_at']}
    proposal.update(draft_id=draft['id'],draft_row_version=draft['row_version'],qualification_kind_ids=[r['qualification_kind_id'] for r in rows('SELECT qualification_kind_id FROM duty_skill WHERE duty_id=%s',[draft['id']])])
    original=get('practice_duty',draft['replaces_duty_id'],True) if draft['replaces_duty_id'] else None
    if original:
        actor.clinic_access(original['clinic_id']);require(body.get('original_row_version')==original['row_version'],'原出诊已变化，请重新核对受影响预约',409)
        if original['publication_state']=='published':
            return duty_action(actor,dict(action='replace',id=original['id'],row_version=original['row_version'],new_duty=proposal,appointment_decisions=body.get('appointment_decisions',[])))
        require(original['publication_state']=='stopped','原出诊已有其他替代安排，请重新核对',409)
    result=duty_action(actor,dict(proposal,action='publish'))
    return dict(result,affected=[],self_service_required=bool(original))
