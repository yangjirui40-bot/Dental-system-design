from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.core import signing
from .db import rows, one, get, insert, update, execute, business_no
from .security import require, BusinessError
from .rules import money, timestamp, version
from .booking import followup
NOTE_FIELDS=['chief_complaint','present_illness','medical_history','examination_summary','tests_summary','diagnosis_summary','management_summary','aftercare','allergy_review']

def load_encounter(actor,pk,lock=True):
    en=get('encounter',int(pk),lock);require(en,'就诊记录不存在',404)
    a=get('appointment',en['appointment_id']);actor.clinic_access(a['clinic_id'])
    if actor.role=='dentist':require(a['dentist_id']==actor.employee,'只能签署本人负责的实际就诊',403)
    return en,a

def consent(actor,en,a,b):
    require(str(b.get('consent_scope','')).strip() and str(b.get('evidence_reference','')).strip(),'须记录患者同意范围与核实依据')
    signer=b.get('signer_contact_id');authority=b.get('authority_id')
    patient=get('patient',a['patient_id']);today=timezone.localdate();age=today.year-patient['birth_date'].year-((today.month,today.day)<(patient['birth_date'].month,patient['birth_date'].day))
    require(age>=18 or signer,'未成年人须核实合法同意主体')
    if signer:
        c=get('patient_contact',int(signer));require(c and c['patient_id']==a['patient_id'] and c['contact_purpose'] in ('guardian','agent'),'联系人不具有临床同意主体身份')
        v=get('patient_authority',int(authority));require(v and v['contact_id']==c['id'] and v['patient_id']==a['patient_id'] and v['permission_scope'] in ('consent','all') and not v['revoked_at'] and v['valid_from']<=timezone.now() and (not v['valid_to'] or v['valid_to']>timezone.now()),'临床同意授权不符或已失效')
    return insert('clinical_consent',dict(encounter_id=en['id'],patient_id=a['patient_id'],signer_contact_id=signer,authority_id=authority,consent_scope=b['consent_scope'],evidence_reference=b['evidence_reference'],verified_by=actor.employee,consented_at=timezone.now()))

def save_treatment(actor,b):
    actor.allow('dentist');en,a=load_encounter(actor,b['encounter_id'])
    prior=one('SELECT * FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
    signing=b['action']=='sign'
    require(b['action'] in ('draft','sign','exception'),'未知临床操作')
    if prior and prior['signature_state']=='signed':require(b.get('correction_reason') and int(b.get('previous_note_id',0))==prior['id'],'已签署记录须明确原版本和更正原因',409)
    if signing:
        attached={r['phase_id'] for r in rows('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s',[a['id']])};provided=[int(r['phase_id']) for r in b.get('phase_results',[])]
        require(set(provided)==attached and len(provided)==len(set(provided)),'请明确本次全部承接阶段的实际实施后结果')
    fields={k:str(b.get(k,'')).strip() for k in NOTE_FIELDS}
    if b['action']=='exception':
        require(str(b.get('exception_reason','')).strip(),'请如实说明尚待核实的事项，不补写虚假的同意依据')
        fields['management_summary']=(fields['management_summary']+'\n待核实事项：'+b['exception_reason']).strip()
    if signing and str(b.get('zero_charge_basis','')).strip():fields['management_summary']+='\n零费用确认依据：'+str(b['zero_charge_basis']).strip().replace('\n','；')
    if signing:require(all(fields.values()),'签署前请补齐主诉、病史、检查、诊断、处置、复诊及过敏核实资料')
    now=timezone.now();note=insert('clinical_note',dict(**fields,encounter_id=en['id'],revision_no=1 if not prior else prior['revision_no']+1,replaces_id=prior['id'] if prior else None,signature_state='signed' if signing else 'draft',signed_by=actor.employee if signing else None,signed_at=now if signing else None,correction_reason=b.get('correction_reason')))
    if signing:execute("UPDATE clinical_note SET signature_state='superseded' WHERE encounter_id=%s AND id<>%s AND signature_state IN ('draft','signed')",[en['id'],note['id']])
    elif prior and prior['signature_state']=='draft':update('clinical_note',prior['id'],{'signature_state':'superseded'})
    if signing:consent(actor,en,a,b)
    require(isinstance(b.get('treatments',[]),list),'实际治疗应为逐项明细')
    existing=rows("""SELECT t.id,t.line_no,tr.*,s.treatment_id AS catalog_id FROM treatment t
      JOIN LATERAL (SELECT * FROM treatment_revision x WHERE x.treatment_id=t.id ORDER BY revision_no DESC LIMIT 1) tr ON true
      JOIN treatment_standard s ON s.id=tr.standard_id WHERE t.encounter_id=%s ORDER BY t.line_no""",[en['id']])
    # t.id and tr.id are distinct identities; use the explicit treatment_id below.
    by_identity={t['treatment_id']:t for t in existing};used=set();prepared=[]
    highest=one('SELECT COALESCE(MAX(line_no),0) AS n FROM treatment WHERE encounter_id=%s',[en['id']])['n']
    for item in b.get('treatments',[]):
        standard=get('treatment_standard',int(item['standard_id']));require(standard,'治疗标准不存在')
        identity=int(item['treatment_id']) if item.get('treatment_id') else None
        if identity:require(identity in by_identity,'治疗明细不属于本次实际就诊',403)
        if not identity and prior:
            candidates=[t for t in existing if t['treatment_id'] not in used and t['catalog_id']==standard['treatment_id']]
            exact=[t for t in candidates if (t['site_description'] or '')==(item.get('site_description') or '')]
            matched=exact[0] if len(exact)==1 else candidates[0] if len(candidates)==1 else None
            if matched:identity=matched['treatment_id']
        require(identity not in used or identity is None,'同一实际治疗不能在本次记录中重复出现')
        if identity:used.add(identity)
        prepared.append((item,standard,identity,by_identity.get(identity)))
    signed_ids={r['treatment_id'] for r in rows("""SELECT DISTINCT tr.treatment_id FROM treatment_revision tr
      JOIN treatment t ON t.id=tr.treatment_id JOIN clinical_note n ON n.id=tr.clinical_note_id
      WHERE t.encounter_id=%s AND n.signed_by IS NOT NULL""",[en['id']])}
    require(signed_ids<=used,'已签署项目不能通过移除行消失；请保留原项目并如实更正数量或未实施结论')
    for item,standard,identity,old in prepared:
        performed=timestamp(item.get('performed_at') or (old['performed_at'] if old else now))
        require(performed<=now,'实际实施时点不能在未来')
        require(standard['approval_state'] in ('approved','retired') and standard['valid_from']<=performed and (not standard['valid_to'] or performed<standard['valid_to']),'须使用实际实施时点有效的已批准标准')
        try:quantity=Decimal(str(item['actual_quantity']))
        except Exception as exc:
            from decimal import InvalidOperation
            if not isinstance(exc,(ValueError,InvalidOperation)):raise
            raise BusinessError('实际数量须为有效数字')
        require(quantity.is_finite() and quantity>=0 and quantity==quantity.quantize(Decimal(10)**(-standard['quantity_scale'])),'实际数量或精度不符')
        price=money(item.get('charged_unit_price',standard['unit_price']));approved=None;basis=None
        if price!=standard['unit_price']:
            approval=one("""SELECT tr.* FROM treatment_revision tr JOIN clinical_note n ON n.id=tr.clinical_note_id
              WHERE n.encounter_id=%s AND n.id=%s AND tr.standard_id=%s AND tr.charged_unit_price=%s
              AND tr.price_approved_by IS NOT NULL ORDER BY tr.id DESC LIMIT 1""",[en['id'],prior['id'] if prior else 0,standard['id'],price])
            if signing:require(approval,'非标准价格须先保存草稿，再由主管在费用批准入口确认')
            if approval:approved=approval['price_approved_by'];basis=approval['price_approval_basis']
        result=item.get('implementation_result','performed');require(result in ('performed','interrupted','deferred'),'实施结论无效');require(result!='deferred' or quantity==0,'未实施项目不能填写已实施数量')
        phase_item=item.get('phase_item_id')
        if phase_item:
            matched=one('SELECT i.* FROM phase_item i JOIN phase_specification s ON s.id=i.phase_specification_id JOIN treatment_phase p ON p.id=s.phase_id JOIN treatment_plan t ON t.id=p.plan_id WHERE i.id=%s AND t.patient_id=%s AND i.standard_id=%s',[phase_item,a['patient_id'],standard['id']]);require(matched,'实际治疗引用的方案项目、患者或标准不符')
        if identity:t=get('treatment',identity)
        else:
            highest+=1;t=insert('treatment',dict(encounter_id=en['id'],line_no=highest))
        insert('treatment_revision',dict(treatment_id=t['id'],revision_no=old['revision_no']+1 if old else 1,replaces_id=old['id'] if old else None,clinical_note_id=note['id'],standard_id=standard['id'],phase_item_id=phase_item,site_description=item.get('site_description'),actual_quantity=quantity,charged_unit_price=price,implementation_result=result,performed_by=actor.employee,performed_at=performed,price_approved_by=approved,price_approval_basis=basis,correction_reason=b.get('correction_reason')))
    if not signing:return dict(note,requires_verification=b['action']=='exception',billing_state='not_issued' if b['action']=='exception' else None)
    for result in b.get('phase_results',[]):
        p=get('treatment_phase',int(result['phase_id']),True);require(p and get('treatment_plan',p['plan_id'])['patient_id']==a['patient_id'],'阶段与就诊患者不符')
        require(one('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s AND phase_id=%s',[a['id'],p['id']]),'只能确认本次承接阶段结果')
        outcome=result['outcome'];require(outcome in ('completed','ready','waiting','paused','terminated'),'阶段结果无效')
        if outcome in ('paused','terminated'):require(result.get('reason'),'暂停或终止须记录原因')
        execute('DELETE FROM phase_reservation WHERE phase_id=%s',[p['id']]);update('treatment_phase',p['id'],dict(progress_outcome=outcome,row_version=p['row_version']+1,completed_by=actor.employee if outcome=='completed' else None,completed_at=now if outcome=='completed' else None,pause_or_end_reason=result.get('reason')))
        if outcome=='ready':followup(actor,a,p['id'])
    latest=one('SELECT * FROM encounter_revision WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
    if not latest['ended_at']:insert('encounter_revision',dict(encounter_id=en['id'],revision_no=latest['revision_no']+1,replaces_id=latest['id'],arrived_at=latest['arrived_at'],started_at=latest['started_at'],ended_at=now,confirmed_by=actor.employee,recorded_at=now))
    # The clinical truth survives a billing failure. A nested savepoint confines
    # rollback to the invoice; UC06 can retry using the existing signed source.
    old_invoice=one('SELECT * FROM invoice WHERE encounter_id=%s',[en['id']])
    if old_invoice:
        current=one("SELECT * FROM invoice_revision WHERE invoice_id=%s AND validity='current'",[old_invoice['id']])
        if current and invoice_matches(en['id'],current['id']):
            execute("UPDATE invoice_revision SET validity='superseded' WHERE invoice_id=%s AND validity IN ('draft','pending')",[old_invoice['id']])
            return dict(note,invoice_id=old_invoice['id'],billing_state='current',billing_unchanged=True)
        execute("UPDATE quarter_report SET confirmation_state='stale' WHERE id IN (SELECT s.report_id FROM report_invoice_source s JOIN invoice_revision r ON r.id=s.invoice_revision_id WHERE r.invoice_id=%s) AND confirmation_state='confirmed'",[old_invoice['id']])
        try:
            with transaction.atomic():proposal=issue_invoice(actor,{'action':'prepare-correction','encounter_id':en['id'],'correction_reason':b.get('correction_reason')})
            return dict(note,invoice_id=old_invoice['id'],proposed_revision_id=proposal['pending_revision']['id'],billing_state='pending_correction',billing_message='实际更正已签署，原有效结算保留，新费用版本待主管核实')
        except (BusinessError,IntegrityError):
            return dict(note,invoice_id=old_invoice['id'],billing_state='pending_correction',billing_message='实际更正已签署，费用核实依据待补齐；原有效结算及历史保留')
    try:
        with transaction.atomic(): invoice=issue_invoice(actor,{'encounter_id':en['id'],'zero_charge_basis':b.get('zero_charge_basis')})
        return dict(note,invoice_id=invoice['id'],billing_state='current')
    except (BusinessError,IntegrityError):return dict(note,billing_state='pending',billing_message='诊疗已签署，结算待按原就诊重试')

def invoice_matches(encounter_id,invoice_revision_id):
    """Compare actual billable facts, not an unrelated prose-note signature time."""
    result=one("""SELECT NOT EXISTS(
      SELECT 1 FROM treatment t JOIN LATERAL
        (SELECT r.*,n.signature_state FROM treatment_revision r JOIN clinical_note n ON n.id=r.clinical_note_id
         WHERE r.treatment_id=t.id ORDER BY r.revision_no DESC LIMIT 1) cur ON true
      LEFT JOIN (SELECT old.* FROM invoice_line line JOIN treatment_revision old ON old.id=line.treatment_revision_id
        WHERE line.invoice_revision_id=%s) prior ON prior.treatment_id=t.id
      WHERE t.encounter_id=%s AND (
       (cur.actual_quantity>0 AND cur.implementation_result IN ('performed','interrupted') AND cur.signature_state='signed')<>(prior.id IS NOT NULL)
       OR (prior.id IS NOT NULL AND ROW(cur.standard_id,COALESCE(cur.site_description,''),cur.actual_quantity,cur.charged_unit_price,cur.implementation_result,cur.performed_at)
          IS DISTINCT FROM ROW(prior.standard_id,COALESCE(prior.site_description,''),prior.actual_quantity,prior.charged_unit_price,prior.implementation_result,prior.performed_at)))) AS matches""",[invoice_revision_id,encounter_id])
    return bool(result['matches'])

def issue_invoice(actor,b):
    en,a=load_encounter(actor,b['encounter_id']);existing=one('SELECT * FROM invoice WHERE encounter_id=%s FOR UPDATE',[en['id']])
    if b.get('action')=='approve-price':
        actor.allow('manager');require(b.get('basis'),'请填写实际批准依据');standard=get('treatment_standard',int(b['standard_id']));require(standard,'项目标准不存在');price=money(b['price'])
        draft=one("SELECT * FROM clinical_note WHERE encounter_id=%s AND signature_state='draft' ORDER BY revision_no DESC LIMIT 1",[en['id']]);require(draft,'须先由牙医保存本次未签署治疗草稿')
        affected=rows('SELECT * FROM treatment_revision WHERE clinical_note_id=%s AND standard_id=%s AND charged_unit_price=%s FOR UPDATE',[draft['id'],standard['id'],price]);require(affected,'草稿中没有对应项目及待批准单价')
        require(all(row['performed_by']!=actor.employee for row in affected),'不能以另一个岗位批准本人实施治疗的非标准价格',403)
        for row in affected:update('treatment_revision',row['id'],dict(price_approved_by=actor.employee,price_approval_basis=b['basis']))
        return {'id':en['id'],'approved_count':len(affected),'approved_by':actor.employee}
    correction=b.get('action')=='correct';prepare=b.get('action')=='prepare-correction'
    if existing and not correction and not prepare:return existing
    if prepare:actor.allow('dentist');require(existing,'先完成原就诊的有效结算')
    if correction:actor.allow('manager');require(b.get('correction_reason'),'更正须填写批准原因')
    note=one("SELECT * FROM clinical_note WHERE encounter_id=%s AND signature_state='signed' ORDER BY revision_no DESC LIMIT 1",[en['id']]);require(note,'实际治疗尚未签署，不能开具有效结算')
    latest=one('SELECT signature_state FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']]);require(latest['signature_state']=='signed','本次临床修订仍在待核实状态，不能据旧记录形成新的有效结算')
    items=rows("SELECT tr.*,s.treatment_name,s.unit_name FROM treatment_revision tr JOIN treatment t ON t.id=tr.treatment_id JOIN treatment_standard s ON s.id=tr.standard_id WHERE t.encounter_id=%s AND tr.clinical_note_id=%s AND tr.actual_quantity>0 AND tr.implementation_result IN ('performed','interrupted') ORDER BY t.line_no",[en['id'],note['id']])
    zero_basis=''
    if not items:
        zero_basis=next((line.split('零费用确认依据：',1)[1].strip() for line in note['management_summary'].splitlines() if line.startswith('零费用确认依据：')),'')
        require(zero_basis,'请先由牙医在签署记录中明确零费用依据，前台或主管不能代为补写')
    total=sum((money(i['actual_quantity']*i['charged_unit_price']) for i in items),Decimal(0));now=timezone.now()
    root=existing or insert('invoice',dict(invoice_no=business_no('INV'),encounter_id=en['id'],first_issued_at=now))
    old=one('SELECT * FROM invoice_revision WHERE invoice_id=%s ORDER BY revision_no DESC LIMIT 1',[root['id']])
    previous_current=one("SELECT id FROM invoice_revision WHERE invoice_id=%s AND validity='current'",[root['id']])
    if correction and old and old['validity'] in ('draft','pending'):
        require(invoice_matches(en['id'],old['id']),'待核对版本与当前实际治疗已不一致，请由牙医重新确认后提交',409)
        execute("UPDATE invoice_revision SET validity='superseded' WHERE invoice_id=%s AND validity='current'",[root['id']])
        rev=update('invoice_revision',old['id'],dict(validity='current',approved_by=actor.employee,approved_at=now,issued_at=now,correction_reason=b['correction_reason']))
    else:
        if not prepare:execute("UPDATE invoice_revision SET validity='superseded' WHERE invoice_id=%s AND validity='current'",[root['id']])
        if old and (not prepare or old['validity'] in ('draft','pending')):update('invoice_revision',old['id'],dict(validity='superseded'))
        rev=insert('invoice_revision',dict(invoice_id=root['id'],revision_no=old['revision_no']+1 if old else 1,replaces_id=old['id'] if old else None,
          validity='pending' if prepare else 'current',total_amount=total,zero_charge_basis=zero_basis or None,issued_by=note['signed_by'],issued_at=now,
          approved_by=actor.employee if correction else None,approved_at=now if correction else None,correction_reason=b.get('correction_reason')))
        for n,item in enumerate(items,1):insert('invoice_line',dict(invoice_revision_id=rev['id'],line_no=n,treatment_revision_id=item['id'],treatment_name_snapshot=item['treatment_name'],unit_name_snapshot=item['unit_name'],quantity_snapshot=item['actual_quantity'],unit_price_snapshot=item['charged_unit_price']))
    if previous_current and not prepare:execute("UPDATE quarter_report SET confirmation_state='stale' WHERE id IN (SELECT report_id FROM report_invoice_source WHERE invoice_revision_id=%s) AND confirmation_state='confirmed'",[previous_current['id']])
    return dict(root,**({'pending_revision':rev} if prepare else {'current_revision':rev}),lines=rows('SELECT * FROM invoice_line WHERE invoice_revision_id=%s ORDER BY line_no',[rev['id']]))

def affected_plan_appointments(plan_id,phases,dependencies):
    """Only changed definitions affect future bookings; stable promises remain."""
    from datetime import timezone as tz
    def when(value):return timestamp(value).astimezone(tz.utc).isoformat() if value else None
    def items_signature(items):return sorted((int(i['standard_id']),i.get('site_description') or '',str(Decimal(str(i['planned_quantity'])).normalize())) for i in items)
    changed=[]
    for item in phases:
        old=one("SELECT s.*,p.phase_no FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id AND r.confirmation_state='confirmed' JOIN treatment_phase p ON p.id=s.phase_id WHERE r.plan_id=%s AND p.phase_no=%s",[plan_id,int(item['phase_no'])])
        if not old:continue
        olditems=rows('SELECT * FROM phase_item WHERE phase_specification_id=%s',[old['id']]);olddeps={r['phase_no'] for r in rows('SELECT p.phase_no FROM phase_dependency d JOIN treatment_phase p ON p.id=d.predecessor_phase_id WHERE d.plan_revision_id=%s AND d.successor_phase_id=%s',[old['plan_revision_id'],old['phase_id']])};newdeps={int(x) for x,y in dependencies if int(y)==int(item['phase_no'])}
        different=any(str(old[k] or '')!=str(item.get(k) or '') for k in ['phase_title','clinical_condition','responsible_clinic_id']) or when(old['earliest_at'])!=when(item.get('earliest_at')) or when(old['latest_at'])!=when(item.get('latest_at')) or items_signature(olditems)!=items_signature(item.get('items',[])) or olddeps!=newdeps
        if different:changed.append(old['phase_id'])
    return rows("SELECT DISTINCT a.id,a.appointment_no FROM appointment a JOIN appointment_phase ap ON ap.appointment_id=a.id WHERE ap.phase_id=ANY(%s::bigint[]) AND a.resolution IN ('booked','arrived')",[changed]) if changed else []

def confirm_saved_plan(actor,b):
    actor.allow('dentist');root=get('treatment_plan',int(b['id']),True);require(root,'计划不存在',404);actor.patient_access(root['patient_id'])
    rev=one('SELECT * FROM plan_revision WHERE plan_id=%s ORDER BY revision_no DESC LIMIT 1 FOR UPDATE',[root['id']]);require(rev and rev['confirmation_state']=='draft' and rev['revision_no']==int(b['version']),'草案版本已变化或已确认，请重新核对',409)
    en,a=load_encounter(actor,b.get('encounter_id') or root['origin_encounter_id']);require(a['patient_id']==root['patient_id'],'同意依据须对应同一患者')
    saved=rows('SELECT s.*,p.phase_no,p.progress_outcome FROM phase_specification s JOIN treatment_phase p ON p.id=s.phase_id WHERE s.plan_revision_id=%s ORDER BY p.phase_no',[rev['id']])
    for p in saved:p['items']=rows('SELECT * FROM phase_item WHERE phase_specification_id=%s',[p['id']])
    deps=rows('SELECT * FROM phase_dependency WHERE plan_revision_id=%s',[rev['id']]);numbers={p['phase_id']:p['phase_no'] for p in saved};edges=[(numbers[e['predecessor_phase_id']],numbers[e['successor_phase_id']]) for e in deps]
    require(not affected_plan_appointments(root['id'],saved,edges),'先按UC03处理定义变化影响的预约；未变化的预约保持原约')
    agreed=consent(actor,en,a,b);now=timezone.now();execute("UPDATE plan_revision SET confirmation_state='superseded' WHERE plan_id=%s AND confirmation_state='confirmed'",[root['id']]);rev=update('plan_revision',rev['id'],dict(confirmation_state='confirmed',consent_id=agreed['id'],confirmed_at=now))
    released={int(x) for x in b.get('released_phase_ids',[])}
    for p in saved:
        if p['progress_outcome'] in ('completed','terminated','paused','booked'):continue
        blocked=one("SELECT d.predecessor_phase_id FROM phase_dependency d JOIN treatment_phase prev ON prev.id=d.predecessor_phase_id WHERE d.plan_revision_id=%s AND d.successor_phase_id=%s AND prev.progress_outcome<>'completed'",[rev['id'],p['phase_id']]);ready=p['phase_id'] in released and not blocked
        state=get('treatment_phase',p['phase_id']);update('treatment_phase',p['phase_id'],dict(progress_outcome='ready' if ready else 'waiting',released_by=actor.employee if ready else None,released_at=now if ready else None,row_version=state['row_version']+1))
        if ready and not one('SELECT id FROM followup_task WHERE phase_id=%s AND closed_at IS NULL',[p['phase_id']]):insert('followup_task',dict(patient_id=root['patient_id'],phase_id=p['phase_id'],responsible_clinic_id=p['responsible_clinic_id'],contact_progress='self_service',opened_at=now,next_contact_at=now+timedelta(days=2),row_version=1))
    root=update('treatment_plan',root['id'],dict(row_version=root['row_version']+1));return dict(root,revision=rev)

def plan_action(actor,b):
    if b.get('confirm_existing_revision'):return confirm_saved_plan(actor,b)
    actor.allow('dentist');en,a=load_encounter(actor,b['encounter_id']);now=timezone.now();existing=get('treatment_plan',int(b['id']),True) if b.get('id') else None
    if b.get('action')=='phase':
        p=get('treatment_phase',int(b['phase_id']),True);require(p and get('treatment_plan',p['plan_id'])['patient_id']==a['patient_id'],'阶段与当前患者不符');outcome=b['outcome'];require(outcome in ('ready','paused','terminated'),'阶段办理结论无效')
        require(p['progress_outcome'] not in ('completed','terminated'),'已结束阶段不能重新放行')
        require(not one('SELECT phase_id FROM phase_reservation WHERE phase_id=%s',[p['id']]),'先处理该阶段未办结预约')
        if outcome=='ready':
            require(b.get('clinical_confirmed'),'须由牙医再次确认临床可约条件');require(not one("SELECT d.predecessor_phase_id FROM phase_dependency d JOIN plan_revision r ON r.id=d.plan_revision_id AND r.confirmation_state='confirmed' JOIN treatment_phase prev ON prev.id=d.predecessor_phase_id WHERE d.successor_phase_id=%s AND prev.progress_outcome<>'completed'",[p['id']]),'前序阶段尚未完成')
        else:
            require(b.get('reason'),'暂停或终止须保留依据')
            latest=one('SELECT ended_at FROM encounter_revision WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
            require(latest and latest['ended_at'],'本次实际接诊尚未结束，请先完成真实实施记录后再暂停或终止阶段')
        result=update('treatment_phase',p['id'],dict(progress_outcome=outcome,released_by=actor.employee if outcome=='ready' else p['released_by'],released_at=now if outcome=='ready' else p['released_at'],pause_or_end_reason=b.get('reason'),row_version=p['row_version']+1))
        if outcome=='ready':
            spec=one("SELECT s.* FROM phase_specification s JOIN plan_revision r ON r.id=s.plan_revision_id AND r.confirmation_state='confirmed' WHERE s.phase_id=%s",[p['id']]);require(spec,'阶段没有已确认定义')
            if not one('SELECT id FROM followup_task WHERE phase_id=%s AND closed_at IS NULL',[p['id']]):insert('followup_task',dict(patient_id=a['patient_id'],phase_id=p['id'],responsible_clinic_id=spec['responsible_clinic_id'],contact_progress='self_service',opened_at=now,next_contact_at=now+timedelta(days=2),row_version=1))
        else:execute('UPDATE followup_task SET closed_at=clock_timestamp(),closing_reason=%s WHERE phase_id=%s AND closed_at IS NULL',[b['reason'],p['id']])
        return result
    if existing:require(existing['patient_id']==a['patient_id'],'计划与患者不符')
    root=existing or insert('treatment_plan',dict(plan_no=business_no('TP'),patient_id=a['patient_id'],origin_encounter_id=en['id'],created_by=actor.employee,created_at=now,row_version=1))
    previous=one('SELECT * FROM plan_revision WHERE plan_id=%s ORDER BY revision_no DESC LIMIT 1',[root['id']]);confirm=b.get('action')=='confirm'
    if existing:
        version(existing,b);require(b.get('change_reason'),'修订计划须说明原因')
        if confirm:require(not affected_plan_appointments(root['id'],b.get('phases',[]),b.get('dependencies',[])),'先按UC03办结定义变化影响的预约，未变化的预约保持原约')
    agreed=consent(actor,en,a,b) if confirm else None
    if previous and confirm:execute("UPDATE plan_revision SET confirmation_state='superseded' WHERE plan_id=%s AND confirmation_state IN ('confirmed','draft')",[root['id']])
    rev=insert('plan_revision',dict(plan_id=root['id'],revision_no=previous['revision_no']+1 if previous else 1,replaces_id=previous['id'] if previous else None,prepared_by=actor.employee,prepared_at=now,confirmation_state='confirmed' if confirm else 'draft',consent_id=agreed['id'] if agreed else None,confirmed_at=now if confirm else None,change_reason=b.get('change_reason')))
    phases=b.get('phases',[]);require(phases,'请至少填写一个治疗阶段');numbers=[int(p['phase_no']) for p in phases];require(len(numbers)==len(set(numbers)),'阶段序号重复')
    old_numbers={r['phase_no'] for r in rows('SELECT phase_no FROM treatment_phase WHERE plan_id=%s',[root['id']])}
    require(old_numbers<=set(numbers),'修订须保留稳定阶段身份，不能从方案中悄然删除既有阶段')
    edges=[(int(e[0]),int(e[1])) for e in b.get('dependencies',[])];from .rules import acyclic;acyclic(numbers,edges);mapped={}
    for item in phases:
        require(isinstance(item.get('clinical_released',False),bool),'阶段临床放行必须为布尔值')
        n=int(item['phase_no']);p=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=%s FOR UPDATE',[root['id'],n]);ready=confirm and bool(item.get('clinical_released')) and not any(y==n for x,y in edges)
        if p:
            if p['progress_outcome'] in ('completed','terminated'):
                oldspec=one('SELECT * FROM phase_specification WHERE phase_id=%s ORDER BY plan_revision_id DESC LIMIT 1',[p['id']]);require(oldspec and oldspec['phase_title']==item['phase_title'] and oldspec['clinical_condition']==item['clinical_condition'] and oldspec['responsible_clinic_id']==int(item['responsible_clinic_id']),'已结束阶段须保留原定义')
                olditems=rows('SELECT standard_id,site_description,planned_quantity FROM phase_item WHERE phase_specification_id=%s ORDER BY id',[oldspec['id']]);require([(x['standard_id'],x.get('site_description') or '',str(x['planned_quantity'].normalize())) for x in olditems]==[(int(x['standard_id']),x.get('site_description') or '',str(Decimal(str(x['planned_quantity'])).normalize())) for x in item.get('items',[])],'已结束阶段的原计划项目不能改写')
            elif confirm and p['progress_outcome'] not in ('paused','booked'):p=update('treatment_phase',p['id'],dict(progress_outcome='ready' if ready else 'waiting',released_by=actor.employee if ready else None,released_at=now if ready else None,row_version=p['row_version']+1))
        else:p=insert('treatment_phase',dict(plan_id=root['id'],phase_no=n,progress_outcome='ready' if ready else 'waiting',released_by=actor.employee if ready else None,released_at=now if ready else None,row_version=1))
        mapped[n]=p['id'];clinic=int(item['responsible_clinic_id']);require(get('clinic',clinic),'阶段承接门店不存在')
        spec=insert('phase_specification',dict(plan_revision_id=rev['id'],phase_id=p['id'],phase_title=item['phase_title'],clinical_condition=item['clinical_condition'],earliest_at=timestamp(item['earliest_at']) if item.get('earliest_at') else None,latest_at=timestamp(item['latest_at']) if item.get('latest_at') else None,responsible_clinic_id=clinic,suggested_clinic_id=clinic,estimated_fee=money(item['estimated_fee']) if item.get('estimated_fee') is not None else None))
        for pi in item.get('items',[]):
            from decimal import InvalidOperation
            standard=get('treatment_standard',int(pi['standard_id']));require(standard and standard['approval_state'] in ('approved','retired'),'方案项目须引用已核实的标准版本')
            try:
                quantity=Decimal(str(pi['planned_quantity']))
                require(quantity.is_finite() and quantity>0 and quantity==quantity.quantize(Decimal(10)**(-standard['quantity_scale'])),'预计数量须为正数并遵守项目计量精度')
            except (InvalidOperation,ValueError):raise BusinessError('预计数量格式或精度不正确')
            insert('phase_item',dict(phase_specification_id=spec['id'],standard_id=standard['id'],site_description=pi.get('site_description'),planned_quantity=quantity))
        if ready and p['progress_outcome']=='ready' and not one('SELECT id FROM followup_task WHERE phase_id=%s AND closed_at IS NULL',[p['id']]):insert('followup_task',dict(patient_id=a['patient_id'],phase_id=p['id'],responsible_clinic_id=clinic,contact_progress='self_service',opened_at=now,next_contact_at=now+timedelta(days=2),row_version=1))
    for predecessor,successor in edges:insert('phase_dependency',dict(plan_revision_id=rev['id'],predecessor_phase_id=mapped[predecessor],successor_phase_id=mapped[successor]))
    if existing:root=update('treatment_plan',root['id'],dict(row_version=existing['row_version']+1))
    return dict(root,revision=rev)
