"""UC12 operating definitions from original Appendix A; never a financial snapshot."""
from collections import Counter,defaultdict
from datetime import datetime,time
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.utils import timezone
from .db import rows,one

TZ=ZoneInfo('Asia/Shanghai')
ACTIVE=('booked','arrived','seen')

def ratio(n,d):
    return round(Decimal(n)*100/Decimal(d),2) if d else None

def operating_report(quarter,clinic=None):
    now=timezone.now();start=datetime.combine(quarter['starts_on'],time.min,TZ);end=datetime.combine(quarter['ends_before'],time.min,TZ)
    appointments=rows("""SELECT a.id,a.appointment_no,a.patient_id,a.dentist_id,a.clinic_id,a.starts_at,a.ends_at,a.resolution,
      c.clinic_name,e.full_name AS dentist_name,
      EXISTS(SELECT 1 FROM appointment_phase p WHERE p.appointment_id=a.id) AS continuation,
      EXISTS(SELECT 1 FROM encounter en JOIN appointment prior ON prior.id=en.appointment_id
        JOIN encounter_revision er ON er.encounter_id=en.id
        WHERE prior.patient_id=a.patient_id AND prior.id<>a.id AND er.started_at<a.starts_at) AS previous_visit,
      event.initiator_kind,event.reason_code,event.reason_description
      FROM appointment a JOIN clinic c ON c.id=a.clinic_id JOIN employee e ON e.id=a.dentist_id
      LEFT JOIN LATERAL (SELECT initiator_kind,reason_code,reason_description FROM appointment_event
        WHERE appointment_id=a.id AND event_kind IN ('cancel','reschedule','clinic_stop','calendar_stop','resource_stop','qualification_stop','no_show','leave') ORDER BY id DESC LIMIT 1) event ON true
      WHERE a.starts_at>=%s AND a.starts_at<%s AND (%s::bigint IS NULL OR a.clinic_id=%s) ORDER BY a.starts_at,a.id""",[start,end,clinic,clinic])
    requests=rows("""SELECT i.appointment_id,i.treatment_id,i.request_description FROM appointment_request_item i
      JOIN appointment a ON a.id=i.appointment_id WHERE a.starts_at>=%s AND a.starts_at<%s
      AND (%s::bigint IS NULL OR a.clinic_id=%s) ORDER BY i.id""",[start,end,clinic,clinic])
    projects=defaultdict(list)
    for item in requests:projects[item['appointment_id']].append(item)
    due=[a for a in appointments if a['ends_at']<=now]
    institutions=[a for a in due if a['resolution']=='unfulfilled' or (a['resolution'] in ('cancelled','rescheduled') and a['initiator_kind']=='organisation')]
    institutional_ids={a['id'] for a in institutions}
    sample=[a for a in due if a['resolution']!='rescheduled' and a['id'] not in institutional_ids]
    cancelled=[a for a in sample if a['resolution']=='cancelled' and a['initiator_kind']=='patient']
    missed=[a for a in sample if a['resolution']=='no_show']
    unresolved=[a for a in sample if a['resolution'] in ('booked','arrived') or (a['resolution']=='cancelled' and not a['initiator_kind'])]
    cancelled_ids = {a['id'] for a in cancelled}
    missed_ids = {a['id'] for a in missed}
    unresolved_ids = {a['id'] for a in unresolved}

    def summary(group):
        n = len(group)
        return {
            'sample_count': n,
            'seen_count': sum(a['resolution'] == 'seen' for a in group),
            'patient_cancellations': sum(a['id'] in cancelled_ids for a in group),
            'verified_no_shows': sum(a['id'] in missed_ids for a in group),
            'unverified_count': sum(a['id'] in unresolved_ids for a in group),
            'cancellation_rate': ratio(sum(a['id'] in cancelled_ids for a in group), n),
            'no_show_rate': ratio(sum(a['id'] in missed_ids for a in group), n),
        }

    month_groups = defaultdict(list)
    for a in sample:
        month_groups[a['starts_at'].astimezone(TZ).strftime('%Y-%m')].append(a)
    months = [
        f"{quarter['calendar_year']}-{month:02}"
        for month in range(quarter['starts_on'].month, quarter['starts_on'].month+3)
    ]
    month_results = []
    for month in months:
        result = summary(month_groups[month])
        other = result['sample_count'] - sum(result[k] for k in (
            'seen_count', 'patient_cancellations', 'verified_no_shows', 'unverified_count',
        ))
        month_results.append(dict(result, month=month, other_count=other))
    dimensions=defaultdict(lambda:defaultdict(list))
    for a in sample:
        kind='阶段接续' if a['continuation'] else '非阶段复诊' if a['previous_visit'] else '初诊'
        hour=a['starts_at'].astimezone(TZ).hour;band='上午' if hour<12 else '下午' if hour<18 else '晚间'
        values={'visit_kind':[kind],'time_band':[band],'clinic':[a['clinic_name']],
          'treatment':sorted({i['request_description'] for i in projects[a['id']]}) or ['按就诊诉求初步检查'],
          'reason':[a['reason_description'] or ('尚待核实' if a in unresolved else a['resolution'])]}
        for dimension,labels in values.items():
            for label in labels:dimensions[dimension][label].append(a)
    strata={dimension:[dict(label=label,**summary(group)) for label,group in groups.items()] for dimension,groups in dimensions.items()}
    def arrangement(a):return {k:a[k] for k in ['id','appointment_no','clinic_name','dentist_name','starts_at','ends_at','resolution','reason_code','reason_description']}
    # Current stage state is independent of the quarter's frozen financial report.
    phases=rows("""SELECT p.id,p.phase_no,p.progress_outcome,p.released_by,p.released_at,s.phase_title,s.earliest_at,s.latest_at,
      s.responsible_clinic_id,c.clinic_name,t.plan_no,
      EXISTS(SELECT 1 FROM phase_reservation r JOIN appointment a ON a.id=r.appointment_id
        WHERE r.phase_id=p.id AND a.resolution IN ('booked','arrived','seen')) AS has_booking,
      EXISTS(SELECT 1 FROM followup_task f WHERE f.phase_id=p.id AND f.closed_at IS NULL
        AND (f.responsible_employee_id IS NOT NULL OR f.responsible_clinic_id IS NOT NULL)
        AND f.contact_progress IN ('self_service','contacted','no_response','needs_assistance') AND f.next_contact_at>%s) AS has_followup,
      EXISTS(SELECT 1 FROM phase_dependency d JOIN treatment_phase prev ON prev.id=d.predecessor_phase_id
        WHERE d.plan_revision_id=r.id AND d.successor_phase_id=p.id AND prev.progress_outcome<>'completed') AS blocked
      FROM treatment_phase p JOIN treatment_plan t ON t.id=p.plan_id
      JOIN phase_specification s ON s.phase_id=p.id JOIN plan_revision r ON r.id=s.plan_revision_id AND r.confirmation_state='confirmed'
      JOIN clinic c ON c.id=s.responsible_clinic_id WHERE (%s::bigint IS NULL OR s.responsible_clinic_id=%s) ORDER BY t.id,p.phase_no""",[now,clinic,clinic])
    actionable=[p for p in phases if p['progress_outcome']=='ready' and p['released_by'] and not p['blocked']
      and (not p['earliest_at'] or p['earliest_at']<=now) and (not p['latest_at'] or p['latest_at']>=now)]
    # Include already-booked clinically released stages in the continuing sample.
    continuing=actionable+[p for p in phases if p['progress_outcome']=='booked' and p['released_by']]
    gaps=[p for p in actionable if not p['has_booking'] and not p['has_followup']]
    followup={'sample_count':len(continuing),'missing_count':len(gaps),'missing_rate':ratio(len(gaps),len(continuing)),
      'state_counts':dict(Counter(p['progress_outcome'] for p in phases)),
      'missing':[{k:p[k] for k in ['id','phase_no','phase_title','plan_no','clinic_name','progress_outcome']} for p in gaps]}
    # Demand is a published appointment request, not an inferred lost patient.
    # Candidate calculations use the exact requested future interval as of now.
    skills=[]
    for a in appointments:
        if a['starts_at']<now or a['resolution'] not in ('booked','unfulfilled'):continue
        required=set();names=[]
        for item in projects[a['id']]:
            names.append(item['request_description'])
            if item['treatment_id']:
                standard=one("""SELECT id FROM treatment_standard WHERE treatment_id=%s AND approval_state IN ('approved','retired')
                  AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s) ORDER BY revision_no DESC LIMIT 1""",[item['treatment_id'],a['starts_at'],a['ends_at']])
                if standard:required.update(x['qualification_kind_id'] for x in rows('SELECT qualification_kind_id FROM standard_qualification WHERE standard_id=%s',[standard['id']]))
        candidates=rows("""SELECT DISTINCT d.dentist_id FROM practice_duty d JOIN employee e ON e.id=d.dentist_id
          JOIN clinic_calendar cal ON cal.id=d.calendar_id AND cal.is_open
          WHERE d.clinic_id=%s AND d.publication_state='published' AND d.starts_at<=%s AND d.ends_at>=%s
          AND cal.starts_at<=%s AND cal.ends_at>=%s AND e.employed_from<=%s AND (e.employed_to IS NULL OR e.employed_to>=%s)
          AND NOT EXISTS(SELECT 1 FROM appointment other WHERE other.id<>%s AND other.dentist_id=d.dentist_id
            AND other.resolution IN ('booked','arrived','seen') AND other.starts_at<%s AND other.ends_at>%s)""",
          [a['clinic_id'],a['starts_at'],a['ends_at'],a['starts_at'],a['ends_at'],a['starts_at'].date(),a['ends_at'].date(),a['id'],a['ends_at'],a['starts_at']])
        qualified=[]
        for candidate in candidates:
            valid=rows("""SELECT qualification_kind_id FROM dentist_qualification WHERE dentist_id=%s
              AND verification_result='verified' AND revoked_at IS NULL AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s)""",[candidate['dentist_id'],a['starts_at'].date(),a['ends_at'].date()])
            if required<={v['qualification_kind_id'] for v in valid}:qualified.append(candidate['dentist_id'])
        resource=one("""SELECT o.id FROM operatory o WHERE o.clinic_id=%s AND o.resource_state='active' AND NOT EXISTS
          (SELECT 1 FROM appointment other WHERE other.id<>%s AND other.operatory_id=o.id AND other.resolution IN ('booked','arrived','seen')
            AND other.starts_at<%s AND other.ends_at>%s) LIMIT 1""",[a['clinic_id'],a['id'],a['ends_at'],a['starts_at']])
        unmet=not qualified or not resource
        skills.append(dict(arrangement(a),projects=names,qualified_dentist_count=len(qualified),resource_available=bool(resource),unmet=unmet,
          reason='无覆盖完整时段的已发布出诊' if not candidates else '有效资格未覆盖所需项目' if not qualified else '无可用完整诊疗位' if not resource else '当前可承接'))
    treatments=rows("""SELECT tr.*,s.treatment_name,s.treatment_id,s.quantity_scale,s.unit_price,s.site_requirement,s.valid_from,s.valid_to,
      s.approval_state,n.signature_state,t.encounter_id,a.id AS appointment_id,a.appointment_no,a.clinic_id,
      EXISTS(SELECT 1 FROM clinical_consent co WHERE co.encounter_id=t.encounter_id) AS has_consent,
      EXISTS(SELECT 1 FROM appointment_request_item ri WHERE ri.appointment_id=a.id AND ri.treatment_id=s.treatment_id) AS requested
      FROM treatment t JOIN LATERAL (SELECT * FROM treatment_revision x WHERE x.treatment_id=t.id ORDER BY revision_no DESC LIMIT 1) tr ON true
      JOIN treatment_standard s ON s.id=tr.standard_id JOIN clinical_note n ON n.id=tr.clinical_note_id
      JOIN encounter en ON en.id=t.encounter_id JOIN appointment a ON a.id=en.appointment_id
      WHERE n.signature_state IN ('signed','draft') AND tr.performed_at>=%s AND tr.performed_at<%s AND tr.performed_at<=%s AND (%s::bigint IS NULL OR a.clinic_id=%s) ORDER BY tr.id""",[start,end,now,clinic,clinic])
    anomalies=[]
    for t in treatments:
        reasons=[]
        if not t['requested'] and not t['phase_item_id']:reasons.append('临床追加项目')
        if t['implementation_result'] in ('interrupted','deferred'):reasons.append('部分中止' if t['implementation_result']=='interrupted' else '未实施暂缓')
        if t['charged_unit_price']!=t['unit_price']:reasons.append('已批准非标准价格' if t['price_approved_by'] and t['price_approval_basis'] else '非标准价格待核实')
        if t['signature_state']!='signed':reasons.append('实际实施尚无有效签署')
        if not t['has_consent']:reasons.append('同意依据尚未齐备')
        if not(t['valid_from']<=t['performed_at'] and (not t['valid_to'] or t['performed_at']<t['valid_to'])):reasons.append('实施时点标准有效性待核实')
        needed={q['qualification_kind_id'] for q in rows('SELECT qualification_kind_id FROM standard_qualification WHERE standard_id=%s',[t['standard_id']])}
        valid={q['qualification_kind_id'] for q in rows("""SELECT qualification_kind_id FROM dentist_qualification WHERE dentist_id=%s
          AND verification_result='verified' AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s)
          AND (revoked_at IS NULL OR revoked_at>%s)""",[t['performed_by'],t['performed_at'].date(),t['performed_at'].date(),t['performed_at']])}
        if not needed<=valid:reasons.append('实施时点所需资格待核实')
        if t['actual_quantity']!=t['actual_quantity'].quantize(Decimal(10)**(-t['quantity_scale'])):reasons.append('实际数量精度不符')
        if t['site_requirement'] and not any(x in t['site_requirement'] for x in ['无需','不要求','不适用']) and not t['site_description']:reasons.append('部位记录待核实')
        if reasons:anomalies.append({k:t[k] for k in ['id','encounter_id','appointment_id','appointment_no','treatment_name','actual_quantity','charged_unit_price','performed_at']}|{'reasons':reasons})
    return {'as_of':now,'quarter_id':quarter['id'],'mode':'live_operations','scope_clinic_id':clinic,
      'definitions':{'due':'原承诺结束时点不晚于查询截止时点，按原承诺日期归期；剔除成功改期旧约及机构原因记录。',
        'rates':'患者主动取消数、核实未到数分别除以同一到期样本。零样本比例为不适用，未核实结果单列。',
        'strata':'多项目预约可进入多个治疗类别，类别样本不得相加代替总样本。非阶段复诊单列，不冒充初诊。',
        'continuity':'当前已放行且进入可约窗口的阶段，以及有效已约阶段。有效跟进须具备责任队列/人员、联系状态及未过期联系时间。',
        'skills':'按原季度内未来预约诉求及完整时段核对当前有效资质、已发布出诊和资源；未排班不等同患者流失。',
        'versions':'运营数据为查询时点快照；季度正式版本仅固定收入、成本、净利润、基金及其财务来源。'},
      'appointments':summary(sample)|{'institutions':len(institutions),'successful_reschedule_old':sum(a['resolution']=='rescheduled' for a in due),
        'months':month_results,'details':[arrangement(a) for a in cancelled+missed+unresolved],'institution_details':[arrangement(a) for a in institutions],'strata':strata},
      'continuity':followup,'skills':{'sample_count':len(skills),'unmet_count':sum(s['unmet'] for s in skills),'rows':skills},
      'standards':{'sample_count':len(treatments),'review_count':len(anomalies),'rows':anomalies}}
