"""Appointment queue, scoped receipt lookup and management summaries."""
from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo
from django.utils import timezone
from .db import rows, one
from .http import endpoint
from .security import authenticate, require, surface_scopes

ZONE = ZoneInfo('Asia/Shanghai')
ACTIVE_APPOINTMENTS = ('booked','arrived')


def appointment_bounds(query):
    bounds=[]
    for key in ('from_date','to_date'):
        raw=query.get(key,'')
        if not raw:
            bounds.append(None)
            continue
        value=date.fromisoformat(raw)
        require(raw==value.isoformat() and value.year<9999,'输入有效的就诊日期')
        bounds.append(value)
    require(not all(bounds) or bounds[0]<=bounds[1],'开始日期不能晚于结束日期')
    start=datetime.combine(bounds[0],time.min,ZONE) if bounds[0] else None
    end=datetime.combine(bounds[1]+timedelta(days=1),time.min,ZONE) if bounds[1] else None
    return start,end


def role_scopes(actor):
    return [scope for scope in surface_scopes(actor.id,'staff') if scope['role_code']==actor.role]


@endpoint
def queue(request, body):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request)
    actor.allow('patient','representative','dentist','reception','manager')
    query=request.GET
    terms=query.get('q','').strip()
    require(len(terms)<=100,'搜索条件过长')
    start,end=appointment_bounds(query)
    order=query.get('order','created')
    require(order in ('created','visit-desc','visit-asc'),'无效的排序方式')
    column='a.created_at' if order=='created' else 'a.starts_at'
    ascending=order=='visit-asc'
    direction='ASC' if ascending else 'DESC'
    comparator='>' if ascending else '<'
    tab=query.get('tab','all')
    require(tab in ('all','current','exceptions','history'),'无效的预约视图')
    clauses=[]
    parameters=[]
    if actor.role in ('patient','representative'):
        patient=actor.account['patient_id'] if actor.role=='patient' else actor.scope['patient_id']
        actor.patient_access(patient,'booking')
        clauses.append('a.patient_id=%s')
        parameters.append(patient)
    elif actor.scope['scope_kind']!='group':
        clauses.append('a.clinic_id=%s')
        parameters.append(actor.clinic)
    if actor.role=='dentist':
        clauses.append('a.dentist_id=%s')
        parameters.append(actor.employee)
    if tab in ('current','exceptions'):
        clauses.append('a.resolution=ANY(%s)')
        parameters.append(list(ACTIVE_APPOINTMENTS) if tab=='current' else ['unfulfilled'])
    if tab=='history':
        clauses.append('NOT (a.resolution=ANY(%s))')
        parameters.append([*ACTIVE_APPOINTMENTS,'unfulfilled'])
    if start:
        clauses.append('a.starts_at>=%s')
        parameters.append(start)
    if end:
        clauses.append('a.starts_at<%s')
        parameters.append(end)
    if terms:
        clauses.append('(p.full_name ILIKE %s OR p.account_no ILIKE %s OR a.appointment_no ILIKE %s OR e.full_name ILIKE %s OR c.clinic_name ILIKE %s)')
        parameters.extend([f'%{terms}%']*5)
    cursor=query.get('cursor','')
    if cursor:
        stamp,separator,cursor_id=cursor.partition('|')
        require(separator and cursor_id.isascii() and cursor_id.isdecimal(),'预约游标无效')
        point=datetime.fromisoformat(stamp)
        require(point.tzinfo is not None and 0<int(cursor_id)<2**63,'预约游标无效')
        clauses.append(f'({column},a.id){comparator}(%s,%s)')
        parameters.extend((point,int(cursor_id)))
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    result=rows("""SELECT a.id,a.appointment_no,a.clinic_id,a.dentist_id,a.patient_id,a.starts_at,a.ends_at,a.created_at,
                         a.request_channel,a.resolution,a.operatory_id,a.row_version,p.full_name AS patient_name,
                         e.full_name AS dentist_name,c.clinic_name,o.operatory_name
                   FROM appointment a JOIN clinic c ON c.id=a.clinic_id
                   JOIN patient p ON p.id=a.patient_id JOIN employee e ON e.id=a.dentist_id
                   JOIN operatory o ON o.id=a.operatory_id"""+where+f' ORDER BY {column} {direction},a.id {direction} LIMIT 41',parameters)
    page=result[:40]
    cursor=None
    if len(result)>40:
        boundary=page[-1]
        cursor=boundary['created_at' if order=='created' else 'starts_at'].isoformat()+'|'+str(boundary['id'])
    return {'items':page,'next':cursor,'order':order,'scope_clinic_id':actor.clinic}


@endpoint
def location(request,body):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request)
    actor.allow('reception','manager')
    number=request.GET.get('number','').strip().upper()
    require(re.fullmatch(r'[A-Z0-9-]{6,40}',number),'输入完整的预约编号')
    available={scope['clinic_id']:scope['id'] for scope in role_scopes(actor) if scope['scope_kind']=='clinic'}
    if actor.scope['scope_kind']=='group':
        available={row['id']:actor.scope['id'] for row in rows('SELECT id FROM clinic')}
    hit=one("""SELECT a.id,a.appointment_no,a.clinic_id,c.clinic_name FROM appointment a JOIN clinic c ON c.id=a.clinic_id
               WHERE upper(a.appointment_no)=%s AND a.clinic_id=ANY(%s::bigint[])""",[number,list(available)])
    require(hit,'已授权门店中未找到该预约编号',404)
    return hit|{'scope_id':available[hit['clinic_id']]}


@endpoint
def clinic_overview(request,body):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request)
    actor.allow('business','director','manager','finance')
    today=timezone.localdate()
    query_start=datetime.combine(today,time.min,ZONE)
    ids=None if actor.scope['scope_kind']=='group' else [s['clinic_id'] for s in role_scopes(actor) if s['scope_kind']=='clinic']
    sites=rows("""SELECT id,clinic_name,clinic_no,postal_address,opened_on,closed_on
                  FROM clinic WHERE (%s::boolean OR id=ANY(%s::bigint[])) ORDER BY id""",[ids is None,ids or []])
    permitted=[site['id'] for site in sites]
    doctors=rows("""SELECT DISTINCT d.clinic_id,e.id,e.full_name
                    FROM practice_duty d JOIN employee e ON e.id=d.dentist_id
                    WHERE d.clinic_id=ANY(%s::bigint[]) AND d.publication_state='published'
                      AND e.employed_from<=%s AND (e.employed_to IS NULL OR e.employed_to>=%s)
                      AND d.starts_at<%s AND d.ends_at>=%s ORDER BY e.full_name""",
                 [permitted,today,today,query_start+timedelta(days=30),query_start-timedelta(days=30)])
    totals={r['clinic_id']:r for r in rows("""SELECT clinic_id,count(distinct patient_id) AS patients,
                       count(*) FILTER (WHERE starts_at>=%s AND starts_at<%s
                         AND resolution IN ('booked','arrived','seen')) AS appointments_today
                     FROM appointment WHERE clinic_id=ANY(%s::bigint[]) GROUP BY clinic_id""",
                   [query_start,query_start+timedelta(days=1),permitted])}
    income={}
    quarter=one('SELECT id,calendar_year,quarter_no,starts_on,ends_before FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[today,today])
    view_income=actor.role in ('director','manager') and quarter is not None
    if view_income:
        income={r['clinic_id']:r['revenue'] for r in rows("""SELECT a.clinic_id,sum(r.total_amount) AS revenue
          FROM invoice_revision r JOIN invoice i ON i.id=r.invoice_id JOIN encounter en ON en.id=i.encounter_id
          JOIN appointment a ON a.id=en.appointment_id
          JOIN LATERAL (SELECT started_at FROM encounter_revision x WHERE x.encounter_id=en.id ORDER BY revision_no DESC LIMIT 1) er ON TRUE
          WHERE r.validity='current' AND a.clinic_id=ANY(%s::bigint[])
            AND (er.started_at AT TIME ZONE 'Asia/Shanghai')::date >= %s
            AND (er.started_at AT TIME ZONE 'Asia/Shanghai')::date < %s GROUP BY a.clinic_id""",
          [permitted,quarter['starts_on'],quarter['ends_before']])}
    for site in sites:
        site['doctors']=[{k:r[k] for k in ('id','full_name')} for r in doctors if r['clinic_id']==site['id']]
        site.update(totals.get(site['id'],{'appointments_today':0,'patients':0}))
        if view_income:
            site['revenue']=income.get(site['id'],0)
    return {'clinics':sites,'date':today,'quarter':quarter}
