"""Resolve an audit reference only when its original use case is authorised."""
from .db import one,get
from .security import require

def resolve(actor,pk,case_roles):
    actor.allow('manager','director')
    event=one('SELECT * FROM audit_event WHERE id=%s AND (%s::bigint IS NULL OR scope_clinic_id=%s)',[pk,actor.clinic,actor.clinic]);require(event,'操作记录不存在或不在当前授权范围',404)
    if actor.scope['scope_kind']!='group':require(event['scope_clinic_id']==actor.clinic,'操作记录超出授权范围',403)
    code=event['object_kind'];require(actor.role in case_roles.get(code,[]),'当前岗位无该原业务的访问权限',403)
    try:identifier=int(event['business_reference'])
    except ValueError:require(False,'该操作没有可打开的业务记录',404)
    operation=event['operation_name'];dataset='';record=None;target={'case':code}
    if code=='UC03':
        if operation=='assign':
            record=get('followup_task',identifier);dataset='followups'
            if record:actor.clinic_access(record['responsible_clinic_id'])
        elif operation=='contact':
            contact=get('followup_contact',identifier);record=get('followup_task',contact['task_id']) if contact else None;dataset='followups'
            if record:actor.clinic_access(record['responsible_clinic_id'])
        else:
            record=get('appointment',identifier);dataset='appointments'
            if record:actor.clinic_access(record['clinic_id'])
    elif code=='UC09':
        record=get('practice_duty',identifier);dataset='duties'
        if record:actor.clinic_access(record['clinic_id'])
    elif code=='UC15':
        dataset='calendars' if operation=='calendar' else 'operatories';record=get('clinic_calendar' if operation=='calendar' else 'operatory',identifier)
        if record:actor.clinic_access(record['clinic_id'])
    elif code=='UC11':
        dataset,table={'source':('cost_revisions','cost_revision'),'review':('allocations','cost_allocation'),
          'submission':('submissions','quarter_submission'),'review-submission':('submissions','quarter_submission')}.get(operation,('',''))
        if table:
            record=get(table,identifier)
            if record and table=='cost_revision':require(actor.scope['scope_kind']=='group' or one('SELECT id FROM cost_allocation WHERE cost_revision_id=%s AND clinic_id=%s',[identifier,actor.clinic]),'来源不在当前门店范围',403)
            elif record:actor.clinic_access(record['clinic_id'])
    elif code=='UC12':
        if operation=='confirm':
            record=get('quarter_report',identifier)
            if record:target.update(quarter=record['quarter_id'],report=record['id'])
        else:record=get('fiscal_quarter',identifier);target['quarter']=identifier
    elif code=='UC10':dataset='catalog' if operation in ('catalog','disable') else 'standard_drafts' if operation=='draft' else 'standards';record=get('treatment_catalog' if dataset=='catalog' else 'treatment_standard',identifier)
    elif code=='UC16':dataset='scopes' if operation in ('grant','revoke') else 'accounts';record=get('account_scope' if dataset=='scopes' else 'user_account',identifier)
    elif code=='UC06':
        if operation=='approve-price':
            record=get('encounter',identifier)
        else:
            invoice=get('invoice',identifier);record=get('encounter',invoice['encounter_id']) if invoice else None
        dataset='encounters'
        if record:
            arrangement=get('appointment',record['appointment_id']);actor.clinic_access(arrangement['clinic_id'])
    require(record,'该记录只能查看操作摘要，原业务无可访问目标',404)
    if dataset:target.update(dataset=dataset,id=record['id'])
    return {'target':target,'previous_version_reference':event['previous_version_reference'],'next_version_reference':event['next_version_reference']}
