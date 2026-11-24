from decimal import Decimal
from django.utils import timezone
from .db import rows, one, get, insert, update, execute, business_no
from .security import require
from .rules import money, split_cost, aggregate_fund

def cost_action(actor,b):
    action=b['action'];now=timezone.now()
    if action=='source':
        actor.allow('finance');allocations=b.get('allocations',[]);split_cost(b['source_amount'],allocations)
        source=get('cost_source',int(b['source_id']),True) if b.get('source_id') else insert('cost_source',dict(source_document_no=b['source_document_no'],source_line_no=int(b.get('source_line_no',1)),cost_category=b['cost_category'],document_date=b['document_date'],evidence_reference=b['evidence_reference']))
        previous=one('SELECT * FROM cost_revision WHERE cost_source_id=%s ORDER BY revision_no DESC LIMIT 1',[source['id']]);require(not previous or b.get('correction_reason'),'费用修订须填写原因')
        rev=insert('cost_revision',dict(cost_source_id=source['id'],revision_no=previous['revision_no']+1 if previous else 1,replaces_id=previous['id'] if previous else None,source_amount=money(b['source_amount']),review_state='pending',prepared_by=actor.employee,prepared_at=now,correction_reason=b.get('correction_reason')))
        for a in allocations:insert('cost_allocation',dict(cost_revision_id=rev['id'],quarter_id=int(a['quarter_id']),dentist_id=int(a['dentist_id']),clinic_id=int(a['clinic_id']),allocated_amount=money(a['allocated_amount']),allocation_basis=a['allocation_basis'],review_state='pending'))
        return rev
    if action=='review':
        actor.allow('manager');a=get('cost_allocation',int(b['id']),True);require(a,'分摊不存在',404);actor.clinic_access(a['clinic_id']);rev=get('cost_revision',a['cost_revision_id'],True);require(rev['prepared_by']!=actor.employee,'不得审批自己录入的费用',403)
        approved=b.get('approved',True);require(approved or b.get('reason'),'异议须填写原因');result=update('cost_allocation',a['id'],dict(review_state='approved' if approved else 'disputed',reviewed_by=actor.employee,reviewed_at=now,objection_reason=b.get('reason')))
        if not approved:
            update('cost_revision',rev['id'],{'review_state':'disputed'})
            if rev['review_state']=='approved':execute("UPDATE quarter_report SET confirmation_state='stale' WHERE id IN (SELECT report_id FROM report_cost_source WHERE cost_revision_id=%s) AND confirmation_state='confirmed'",[rev['id']])
        elif not one("SELECT id FROM cost_allocation WHERE cost_revision_id=%s AND review_state<>'approved'",[rev['id']]):
            allrows=rows('SELECT * FROM cost_allocation WHERE cost_revision_id=%s',[rev['id']]);split_cost(rev['source_amount'],allrows)
            if rev['replaces_id']:update('cost_revision',rev['replaces_id'],{'review_state':'superseded'});execute("UPDATE quarter_report SET confirmation_state='stale' WHERE id IN (SELECT report_id FROM report_cost_source WHERE cost_revision_id=%s) AND confirmation_state='confirmed'",[rev['replaces_id']])
            update('cost_revision',rev['id'],dict(review_state='approved',approved_by=actor.employee,approved_at=now))
        return result
    if action=='submission':
        actor.allow('finance');q=int(b['quarter_id']);d=int(b['dentist_id']);c=int(b['clinic_id']);old=one('SELECT * FROM quarter_submission WHERE quarter_id=%s AND dentist_id=%s AND clinic_id=%s ORDER BY revision_no DESC LIMIT 1',[q,d,c])
        return insert('quarter_submission',dict(quarter_id=q,dentist_id=d,clinic_id=c,revision_no=old['revision_no']+1 if old else 1,replaces_id=old['id'] if old else None,supplies_complete=bool(b['supplies_complete']),operating_complete=bool(b['operating_complete']),review_state='pending'))
    require(action=='review-submission','未知费用操作');actor.allow('manager');s=get('quarter_submission',int(b['id']),True);require(s,'报送不存在',404);actor.clinic_access(s['clinic_id'])
    creator=one("SELECT u.employee_id FROM audit_event a JOIN user_account u ON u.id=a.account_id WHERE a.object_kind='UC11' AND a.operation_name='submission' AND a.business_reference=%s ORDER BY a.id LIMIT 1",[str(s['id'])]);require(creator and creator['employee_id']!=actor.employee,'不得复核本人报送或来源不明的齐备声明',403)
    return update('quarter_submission',s['id'],dict(review_state='approved' if b.get('approved',True) else 'disputed',reviewed_by=actor.employee,reviewed_at=now))

def calculate(actor,quarter_id,clinic_override=None):
    q=get('fiscal_quarter',int(quarter_id));require(q,'季度不存在',404);actor.allow('manager','director')
    clinic=actor.clinic if actor.scope['scope_kind']!='group' else None
    if clinic_override:
        clinic=int(clinic_override);actor.clinic_access(clinic);require(get('clinic',clinic),'门店不存在',404)
    earnings=rows("""SELECT i.id AS invoice_id,r.id AS revision_id,er.id AS encounter_revision_id,a.clinic_id,a.dentist_id,r.total_amount
      FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id AND r.validity='current'
      JOIN encounter e ON e.id=i.encounter_id JOIN appointment a ON a.id=e.appointment_id
      JOIN LATERAL (SELECT * FROM encounter_revision x WHERE x.encounter_id=e.id ORDER BY revision_no DESC LIMIT 1) er ON true
      WHERE (er.started_at AT TIME ZONE 'Asia/Shanghai')::date>=%s AND (er.started_at AT TIME ZONE 'Asia/Shanghai')::date<%s
      AND (%s::bigint IS NULL OR a.clinic_id=%s)""",[q['starts_on'],q['ends_before'],clinic,clinic])
    costs=rows("""SELECT a.*,s.cost_category FROM cost_allocation a JOIN cost_revision r ON r.id=a.cost_revision_id JOIN cost_source s ON s.id=r.cost_source_id WHERE a.quarter_id=%s AND a.review_state='approved' AND r.review_state='approved' AND (%s::bigint IS NULL OR a.clinic_id=%s)""",[q['id'],clinic,clinic])
    combos=rows("""SELECT DISTINCT dentist_id,clinic_id FROM practice_duty WHERE confirmed_at IS NOT NULL AND starts_at<%s::date AND ends_at>%s::date AND (%s::bigint IS NULL OR clinic_id=%s)
       UNION SELECT DISTINCT dentist_id,clinic_id FROM cost_allocation WHERE quarter_id=%s AND (%s::bigint IS NULL OR clinic_id=%s)""",[q['ends_before'],q['starts_on'],clinic,clinic,q['id'],clinic,clinic])
    pairs={(r['dentist_id'],r['clinic_id']) for r in combos+earnings+costs};stats={pair:dict(dentist_id=pair[0],clinic_id=pair[1],revenue=Decimal(0),supplies_cost=Decimal(0),operating_expense=Decimal(0)) for pair in pairs}
    for r in earnings:stats[r['dentist_id'],r['clinic_id']]['revenue']+=r['total_amount']
    for r in costs:stats[r['dentist_id'],r['clinic_id']]['supplies_cost' if r['cost_category']=='supplies' else 'operating_expense']+=r['allocated_amount']
    issues=[];submissions=[]
    for pair in sorted(pairs):
        s=one('SELECT * FROM quarter_submission WHERE quarter_id=%s AND dentist_id=%s AND clinic_id=%s ORDER BY revision_no DESC LIMIT 1',[q['id'],*pair])
        if not s or s['review_state']!='approved' or not s['supplies_complete'] or not s['operating_complete']:issues.append(f'牙医{pair[0]}／门店{pair[1]}两类费用尚未明确报齐并复核')
        else:submissions.append(s)
        row=stats[pair];row['net_profit']=row['revenue']-row['supplies_cost']-row['operating_expense'];row['dentist_name']=get('employee',pair[0])['full_name'];row['clinic_name']=get('clinic',pair[1])['clinic_name']
    pending=one("""SELECT count(*) AS n FROM encounter e JOIN appointment a ON a.id=e.appointment_id JOIN LATERAL (SELECT * FROM encounter_revision x WHERE x.encounter_id=e.id ORDER BY revision_no DESC LIMIT 1) er ON true
     WHERE er.started_at>=%s::date AND er.started_at<%s::date AND (%s::bigint IS NULL OR a.clinic_id=%s)
     AND (er.ended_at IS NULL OR NOT EXISTS (SELECT 1 FROM invoice i JOIN invoice_revision r ON r.invoice_id=i.id WHERE i.encounter_id=e.id AND r.validity='current'))""",[q['starts_on'],q['ends_before'],clinic,clinic])
    if pending['n']:issues.append(f"{pending['n']}次实际就诊尚未结束或完成结算")
    from .clinical import invoice_matches
    for earning in earnings:
        current=one("""SELECT en.id,n.signature_state FROM invoice i JOIN encounter en ON en.id=i.encounter_id
          JOIN LATERAL (SELECT signature_state FROM clinical_note WHERE encounter_id=en.id ORDER BY revision_no DESC LIMIT 1) n ON true
          WHERE i.id=%s""",[earning['invoice_id']])
        if current and (current['signature_state']!='signed' or not invoice_matches(current['id'],earning['revision_id'])):
            issues.append(f"结算来源{earning['invoice_id']}存在待核实临床修订或尚未批准的费用更正")
    unreviewed=one("SELECT count(*) AS n FROM cost_allocation a JOIN cost_revision r ON r.id=a.cost_revision_id WHERE a.quarter_id=%s AND r.review_state IN ('draft','pending','disputed') AND (%s::bigint IS NULL OR a.clinic_id=%s)",[q['id'],clinic,clinic])
    if unreviewed['n']:issues.append('费用来源存在未复核或异议项')
    total,fund=aggregate_fund(r['net_profit'] for r in stats.values())
    from .operations import operating_report
    operational=operating_report(q,clinic)
    if operational['appointments']['unverified_count']:issues.append(f"{operational['appointments']['unverified_count']}条到期预约结果尚未核实")
    return dict(id=q['id'],quarter=q,scope_kind='group' if clinic is None else 'clinic',clinic_id=clinic,rows=list(stats.values()),group_net_profit=total,incentive_fund=money(fund) if clinic is None else None,issues=issues,confirmation_state='ready' if not issues else 'provisional',operations=operational),earnings,costs,submissions

def report_action(actor,b):
    data,earnings,costs,submissions=calculate(actor,b['quarter_id'],b.get('clinic_id'))
    if b.get('action')!='confirm':return data
    actor.allow('director');require(actor.scope['scope_kind']=='group' and data['scope_kind']=='group','集团正式确认须使用完整集团范围',403);require(not data['issues'],'资料未齐，只能暂算，不能正式确认')
    one('SELECT id FROM fiscal_quarter WHERE id=%s FOR UPDATE',[data['id']]);old=one('SELECT * FROM quarter_report WHERE quarter_id=%s ORDER BY revision_no DESC LIMIT 1',[data['id']])
    if old:require(b.get('previous_report_id')==old['id'],'正式确认版本已变化，请核对原版本',409);update('quarter_report',old['id'],dict(confirmation_state='superseded'))
    now=timezone.now();report=insert('quarter_report',dict(quarter_id=data['id'],revision_no=old['revision_no']+1 if old else 1,replaces_id=old['id'] if old else None,as_of=now,confirmation_state='confirmed',group_net_profit=data['group_net_profit'],incentive_fund=data['incentive_fund'],confirmed_by=actor.employee,confirmed_at=now))
    for r in data['rows']:insert('dentist_performance',dict(report_id=report['id'],**{k:r[k] for k in ['dentist_id','clinic_id','revenue','supplies_cost','operating_expense']}))
    for r in earnings:insert('report_invoice_source',dict(report_id=report['id'],invoice_revision_id=r['revision_id'],encounter_revision_id=r['encounter_revision_id']))
    for cid in {r['cost_revision_id'] for r in costs}:insert('report_cost_source',dict(report_id=report['id'],cost_revision_id=cid))
    for r in submissions:insert('report_submission_source',dict(report_id=report['id'],submission_id=r['id']))
    return dict(report,rows=data['rows'])
