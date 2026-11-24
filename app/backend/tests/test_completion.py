"""Independent acceptance regressions for the final UC03/05/09/12/15/17 flows.
Every test writes only inside a rolled-back transaction in an isolated database.
"""
import json,unittest
from unittest.mock import patch
from datetime import timedelta
import test_integration as base
from core.db import get,one,rows,execute,update,insert
from core.clinical import NOTE_FIELDS
from core.operations import operating_report
from django.utils import timezone

class CompletionTests(unittest.TestCase):
    setUpClass=classmethod(base.WorkflowTests.setUpClass.__func__)
    post=base.WorkflowTests.post
    booking=base.WorkflowTests.booking
    rollback=base.WorkflowTests.rollback
    def setUp(self):
        base.WorkflowTests.setUp(self)
        self.test_22_complete_clinical_invoice=lambda:base.WorkflowTests.test_22_complete_clinical_invoice(self)
    def ok(self,response):
        self.assertEqual(response.status_code,200,response.content)
        return response.json()
    def signed(self):
        self.test_22_complete_clinical_invoice()
        en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1')
        note=one('SELECT * FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
        treatment=one('SELECT r.* FROM treatment_revision r JOIN treatment t ON t.id=r.treatment_id WHERE t.encounter_id=%s ORDER BY r.id DESC LIMIT 1',[en['id']])
        invoice=one("SELECT r.* FROM invoice_revision r JOIN invoice i ON i.id=r.invoice_id WHERE i.encounter_id=%s AND r.validity='current'",[en['id']])
        body=dict(action='sign',encounter_id=en['id'],previous_note_id=note['id'],correction_reason='核实后补正文字',**{k:note[k] for k in NOTE_FIELDS},consent_scope='更正内容已说明',evidence_reference='当次同意核实',treatments=[{k:treatment[k] for k in ['treatment_id','standard_id','site_description','actual_quantity','charged_unit_price','implementation_result']}])
        return en,note,treatment,invoice,body
    def draft(self,changed=False):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));d=get('practice_duty',b['duty_id'])
        proposal={k:d[k] for k in ['clinic_id','dentist_id','calendar_id','starts_at','ends_at']}
        if changed:
            proposal['starts_at']=d['starts_at']+timedelta(hours=1)
        proposal.update(action='draft',original_id=d['id'],qualification_kind_ids=[])
        draft=self.ok(self.post('business','UC09',proposal))
        return b,a,d,draft,proposal
    def test_audit_filters_and_versions(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b))
        self.ok(self.post('patient','UC03',dict(action='cancel',id=a['id'],row_version=1,reason='患者电话要求取消')))
        data=self.ok(self.clients['director'].get('/api/audit',dict(business_type='UC03',reference=a['id'],operation='cancel',result='completed')))
        self.assertEqual(len(data['items']),1);event=data['items'][0]
        self.assertEqual(event['previous_version_reference'],f"a:{a['id']}:1")
        self.assertEqual(event['next_version_reference'],f"a:{a['id']}:2")
        self.assertEqual(self.clients['director'].get('/api/audit?date_from=bad').status_code,422)
        self.assertEqual(self.clients['director'].get('/api/audit?date_from=2026-12-01&date_to=2026-01-01').status_code,422)
    def test_unchanged_coordination_keeps_promise(self):
        b,a,d,draft,proposal=self.draft()
        self.assertEqual(get('practice_duty',d['id'])['publication_state'],'published')
        preview=self.ok(self.clients['business'].post('/api/duties/preview',data=json.dumps(proposal,default=str),content_type='application/json'))
        self.assertEqual(preview['agreement_count'],0)
        r=self.ok(self.post('business','UC09',dict(action='publish-draft',draft_id=draft['id'],row_version=draft['row_version'],original_row_version=d['row_version'])))
        self.assertEqual(r['id'],draft['id']);current=get('appointment',a['id'])
        self.assertEqual(current['appointment_no'],a['appointment_no']);self.assertEqual(current['starts_at'],b['starts_at']);self.assertEqual(current['duty_id'],draft['id'])
    def test_changed_coordination_is_atomic_until_patient_agrees(self):
        b,a,d,draft,p=self.draft(changed=True)
        body=dict(action='publish-draft',draft_id=draft['id'],row_version=draft['row_version'],original_row_version=d['row_version'])
        self.assertEqual(self.post('business','UC09',body).status_code,409)
        self.assertEqual(get('practice_duty',d['id'])['publication_state'],'published');self.assertEqual(get('appointment',a['id'])['resolution'],'booked')
        replacement=dict(b,starts_at=p['starts_at'],ends_at=p['starts_at']+timedelta(minutes=30));replacement.pop('action')
        body['appointment_decisions']=[dict(appointment_id=a['id'],row_version=1,confirmation_basis='患者明确同意新时段',replacement=replacement)]
        self.ok(self.post('business','UC09',body));self.assertEqual(get('appointment',a['id'])['resolution'],'rescheduled')
        new=one('SELECT * FROM appointment WHERE previous_appointment_id=%s',[a['id']]);self.assertEqual(new['duty_id'],draft['id'])
        event=one("SELECT * FROM appointment_event WHERE appointment_id=%s AND event_kind='reschedule'",[a['id']]);self.assertEqual(event['initiator_kind'],'organisation')
    def test_invalid_coordination_can_be_saved_but_not_published(self):
        b,a,d,draft,p=self.draft();p['starts_at']=d['starts_at']-timedelta(hours=5)
        preview=self.ok(self.clients['business'].post('/api/duties/preview',data=json.dumps(p,default=str),content_type='application/json'))
        self.assertFalse(preview['can_publish']);self.assertTrue(preview['issues']);self.assertEqual(get('practice_duty',d['id'])['publication_state'],'published')
    def test_emergency_operatory_preserves_followup_and_blocks_booking(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));op=get('operatory',b['operatory_id'])
        body={k:op[k] for k in ['id','clinic_id','row_version','operatory_code','operatory_name']};body.update(action='operatory',resource_state='maintenance')
        self.assertEqual(self.post('manager','UC15',body).status_code,409)
        self.assertEqual(get('operatory',op['id'])['resource_state'],'active')
        body.update(change_mode='immediate',impact_acknowledged=True,unavailable_reason='已确认设备故障停用')
        r=self.ok(self.post('manager','UC15',body));self.assertIn(a['id'],r['affected_appointment_ids'])
        self.assertEqual(get('appointment',a['id'])['resolution'],'unfulfilled');self.assertIsNotNone(one('SELECT * FROM followup_task WHERE source_appointment_id=%s AND closed_at IS NULL',[a['id']]))
        self.assertEqual(self.post('patient','UC02',b).status_code,422)
        alternative=one("SELECT id FROM operatory WHERE clinic_id=%s AND id<>%s AND resource_state='active'",[op['clinic_id'],op['id']]);b['operatory_id']=alternative['id']
        self.ok(self.post('patient','UC03',dict(action='reschedule',id=a['id'],row_version=2,reason='选择故障后的可用时段',replacement=b)))
        self.assertIsNone(one('SELECT * FROM followup_task WHERE source_appointment_id=%s AND closed_at IS NULL',[a['id']]))
    def test_emergency_requires_explicit_acknowledgement(self):
        b=self.booking();op=get('operatory',b['operatory_id']);body={k:op[k] for k in ['id','clinic_id','row_version','operatory_code','operatory_name']}
        body.update(action='operatory',resource_state='maintenance',change_mode='immediate',unavailable_reason='真实设备故障')
        self.assertEqual(self.post('manager','UC15',body).status_code,422);self.assertEqual(get('operatory',op['id'])['resource_state'],'active')
    def test_immediate_calendar_closure_retains_promises_as_unfulfilled(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));d=get('practice_duty',b['duty_id']);cal=get('clinic_calendar',d['calendar_id'])
        body={k:cal[k] for k in ['id','clinic_id','row_version','work_date','session_no']};body.update(action='calendar',is_open=False,change_mode='immediate',impact_acknowledged=True,unavailable_reason='突发停电无法营业')
        self.ok(self.post('manager','UC15',body));self.assertEqual(get('practice_duty',d['id'])['publication_state'],'stopped');self.assertEqual(get('appointment',a['id'])['resolution'],'unfulfilled')
    def test_staff_patient_cancellation_is_not_institutional(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b))
        self.ok(self.post('reception','UC03',dict(action='cancel',id=a['id'],row_version=1,reason='患者来电取消',initiator_kind='patient')))
        event=one('SELECT * FROM appointment_event WHERE appointment_id=%s',[a['id']]);self.assertEqual(event['initiator_kind'],'patient')
        q=one('SELECT * FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[b['starts_at'].date(),b['starts_at'].date()])
        with patch('core.operations.timezone.now',return_value=b['ends_at']+timedelta(seconds=1)):
            report=operating_report(q,b['clinic_id'])
        self.assertEqual(report['appointments']['patient_cancellations'],1)
    def test_empty_denominators_are_not_fabricated_zero_rates(self):
        q=one('SELECT * FROM fiscal_quarter ORDER BY starts_on LIMIT 1')
        report=operating_report(q);self.assertEqual(report['appointments']['sample_count'],0);self.assertIsNone(report['appointments']['no_show_rate'])
    def test_followup_without_future_deadline_is_missing(self):
        base.WorkflowTests.test_28_plan_phase_and_cancellation_continuity(self)
        q=one('SELECT * FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[timezone.localdate(),timezone.localdate()]);p=one('SELECT * FROM treatment_phase WHERE phase_no=1 ORDER BY id DESC LIMIT 1')
        before=operating_report(q);self.assertEqual(before['continuity']['missing_count'],0)
        execute('UPDATE followup_task SET next_contact_at=now()-interval \'1 minute\' WHERE phase_id=%s',[p['id']])
        after=operating_report(q);self.assertEqual(after['continuity']['missing_count'],1)
    def test_representative_invoice_only_and_revocation(self):
        account=one("SELECT * FROM user_account WHERE login_name='representative'")
        execute("UPDATE patient_authority SET permission_scope='invoices' WHERE authorized_account_id=%s",[account['id']])
        ws=self.ok(self.clients['representative'].get('/api/workspace'));self.assertTrue(ws['capabilities']['can_view_invoices']);self.assertFalse(ws['capabilities']['can_book']);self.assertFalse(ws['capabilities']['can_view_stages'])
        execute('UPDATE patient_authority SET revoked_at=now() WHERE authorized_account_id=%s',[account['id']]);self.assertEqual(self.clients['representative'].get('/api/workspace').status_code,403)
    def test_prose_correction_keeps_treatment_time_and_invoice(self):
        en,n,t,invoice,b=self.signed();b['management_summary']='补正文字说明，实际实施未变化'
        r=self.ok(self.post('dentist','UC05',b));self.assertTrue(r['billing_unchanged']);current=one('SELECT * FROM treatment_revision WHERE treatment_id=%s ORDER BY revision_no DESC LIMIT 1',[t['treatment_id']])
        self.assertEqual(current['performed_at'],t['performed_at']);self.assertEqual(get('invoice_revision',invoice['id'])['validity'],'current');self.assertEqual(one('SELECT count(*) n FROM treatment WHERE encounter_id=%s',[en['id']])['n'],1)
    def test_signed_line_cannot_disappear_when_reordering(self):
        en,n,t,invoice,b=self.signed();b['treatments']=[]
        self.assertEqual(self.post('dentist','UC05',b).status_code,422);self.assertEqual(get('clinical_note',n['id'])['signature_state'],'signed')
    def test_financial_change_creates_proposal_then_approves_same_version(self):
        en,n,t,invoice,b=self.signed();b['treatments'][0]['actual_quantity']=2
        r=self.ok(self.post('dentist','UC05',b));self.assertEqual(r['billing_state'],'pending_correction');pending=get('invoice_revision',r['proposed_revision_id'])
        self.assertEqual(pending['validity'],'pending');self.assertEqual(get('invoice_revision',invoice['id'])['validity'],'current')
        approved=self.ok(self.post('manager','UC06',dict(action='correct',encounter_id=en['id'],correction_reason='核实实际数量及费用')))
        self.assertEqual(approved['current_revision']['id'],pending['id']);self.assertEqual(approved['current_revision']['total_amount'],str(t['charged_unit_price']*2));self.assertEqual(get('invoice_revision',invoice['id'])['validity'],'superseded')
    def test_unverified_fact_draft_does_not_issue_invoice(self):
        en,n,t,invoice,b=self.signed();b.update(action='exception',exception_reason='补正事项同意依据尚待核实');b.pop('consent_scope');b.pop('evidence_reference')
        r=self.ok(self.post('dentist','UC05',b));self.assertTrue(r['requires_verification']);self.assertEqual(get('invoice_revision',invoice['id'])['validity'],'current')
        self.assertEqual(self.post('manager','UC06',dict(action='correct',encounter_id=en['id'],correction_reason='试图用旧记录开新费用')).status_code,422)
    def test_frozen_report_reads_saved_sources_and_manager_has_no_group_fund(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self)
        report=one('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 1');cost=one('SELECT * FROM cost_revision ORDER BY id DESC LIMIT 1')
        update('cost_revision',cost['id'],dict(review_state='superseded'))
        data=self.ok(self.clients['director'].get('/api/reports/'+str(report['id'])))
        self.assertEqual(data['source_mode'],'frozen_financial_versions');self.assertEqual(data['sources']['costs'][0]['cost_revision_id'],cost['id']);self.assertEqual(data['sources']['costs'][0]['allocated_amount'],'80.50')
        manager=self.ok(self.clients['manager'].get('/api/reports/'+str(report['id'])));self.assertNotIn('incentive_fund',manager);self.assertNotIn('group_net_profit',manager)
    def test_clinical_draft_blocks_formal_financial_confirmation(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self)
        en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');note=one("SELECT * FROM clinical_note WHERE encounter_id=%s AND signature_state='signed'",[en['id']]);t=one('SELECT * FROM treatment_revision ORDER BY id DESC LIMIT 1')
        b=dict(action='draft',encounter_id=en['id'],previous_note_id=note['id'],correction_reason='临床事实核实中',treatments=[{k:t[k] for k in ['treatment_id','standard_id','actual_quantity','charged_unit_price','implementation_result']}])
        self.ok(self.post('dentist','UC05',b));report=one('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 1')
        data=self.ok(self.clients['director'].get('/api/reports?quarter_id='+str(report['quarter_id'])));self.assertTrue(any('临床修订' in i for i in data['issues']))
        self.assertEqual(self.post('director','UC12',dict(action='confirm',quarter_id=report['quarter_id'],previous_report_id=report['id'])).status_code,422)

    def test_billing_review_is_scoped_and_has_no_clinical_narrative(self):
        en,n,t,invoice,b=self.signed()
        data=self.ok(self.clients['manager'].get('/api/billing/'+str(en['id'])))
        self.assertEqual(data['items'][0]['treatment_id'],t['treatment_id']);self.assertFalse(data['clinical_narrative_included']);self.assertNotIn('chief_complaint',json.dumps(data))
        self.assertEqual(self.clients['finance'].get('/api/billing/'+str(en['id'])).status_code,403)
        self.assertEqual(self.clients['patient'].get('/api/billing/'+str(en['id'])).status_code,403)
    def test_independent_standard_approval_checks_real_employee(self):
        c=self.ok(self.post('business','UC10',dict(action='catalog',treatment_code='TEST-INDEPENDENT',treatment_name='独立批准测试')))
        b=dict(action='draft',treatment_id=c['id'],treatment_name='独立批准测试',unit_name='次',quantity_scale=0,unit_price=50,site_requirement='核实部位',duration_minutes=30,valid_from=str(timezone.now()+timedelta(days=1)))
        standard=self.ok(self.post('business','UC10',b))
        employee=one("SELECT employee_id FROM user_account WHERE login_name='business'")['employee_id']
        from core.security import token
        from django.test import Client
        account=one("SELECT * FROM user_account WHERE login_name='business'");role=one("SELECT id FROM access_role WHERE role_code='director'")
        scope=insert('account_scope',dict(account_id=account['id'],role_id=role['id'],granted_by=one("SELECT id FROM user_account WHERE login_name='director'")['id'],granted_at=timezone.now(),scope_kind='group'))
        client=Client(HTTP_AUTHORIZATION='Bearer '+token(account,scope['id']))
        response=client.post('/api/use-cases/UC10',data=json.dumps(dict(action='approve',id=standard['id'])),content_type='application/json',HTTP_IDEMPOTENCY_KEY=__import__('uuid').uuid4().hex)
        self.assertEqual(response.status_code,422,response.content)
        self.assertEqual(get('treatment_standard',standard['id'])['approval_state'],'draft')
    def test_revoking_unique_required_qualification_blocks_future_promises(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b))
        required=one('SELECT qualification_kind_id FROM standard_qualification WHERE standard_id=%s',[b['standard_ids'][0]])
        if required is None:
            required=one('SELECT qualification_kind_id FROM dentist_qualification WHERE dentist_id=%s LIMIT 1',[b['dentist_id']])
            execute('INSERT INTO duty_skill(duty_id,qualification_kind_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',[b['duty_id'],required['qualification_kind_id']])
        qualification=one("SELECT * FROM dentist_qualification WHERE dentist_id=%s AND qualification_kind_id=%s AND verification_result='verified' AND revoked_at IS NULL ORDER BY id LIMIT 1",[b['dentist_id'],required['qualification_kind_id']])
        execute("UPDATE dentist_qualification SET verification_result='rejected' WHERE dentist_id=%s AND qualification_kind_id=%s AND id<>%s",[b['dentist_id'],required['qualification_kind_id'],qualification['id']])
        r=self.ok(self.post('business','UC08',dict(action='revoke',id=qualification['id'],reason='核实证照已经撤销')))
        self.assertIn(a['id'],r['affected_appointment_ids']);self.assertEqual(get('appointment',a['id'])['resolution'],'unfulfilled')
        self.assertIsNotNone(one('SELECT id FROM followup_task WHERE source_appointment_id=%s AND closed_at IS NULL',[a['id']]))

    def test_duplicate_candidate_requires_distinct_identity_verification(self):
        patient=one("SELECT * FROM patient WHERE account_no='P-DEMO-001'")
        body=dict(action='save',emergency_name='合成紧急联系人',emergency_phone='13900009999',emergency_relationship='亲属',full_name=patient['full_name'],birth_date='1995-07-21',phone=patient['phone'],billing_address='不同真实身份核实后的教学地址')
        count=one('SELECT count(*) n FROM patient')['n']
        self.assertEqual(self.post('reception','UC01',body).status_code,409);self.assertEqual(one('SELECT count(*) n FROM patient')['n'],count)
        body.update(identity_confirmed=True,identity_check_basis='前台已核实出生日期及账单地址，确认为独立患者而非合并')
        new=self.ok(self.post('reception','UC01',body));self.assertNotEqual(new['id'],patient['id']);self.assertNotEqual(new['account_no'],patient['account_no'])
    def test_disabled_account_keeps_responsibility_until_manager_handover(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));d=get('practice_duty',b['duty_id'])
        self.ok(self.post('manager','UC09',dict(action='stop',id=d['id'],row_version=d['row_version'],reason='教学核实停诊')))
        task=one('SELECT * FROM followup_task WHERE source_appointment_id=%s',[a['id']]);old=one("SELECT * FROM user_account WHERE login_name='reception'")
        update('followup_task',task['id'],dict(responsible_employee_id=old['employee_id']))
        disabled=self.ok(self.post('director','UC16',dict(action='disable',id=old['id'])))
        self.assertTrue(disabled['handover_required']);self.assertEqual(get('followup_task',task['id'])['responsible_employee_id'],old['employee_id']);self.assertEqual(self.clients['reception'].get('/api/workspace').status_code,401)
        manager=one("SELECT * FROM user_account WHERE login_name='manager'")
        result=self.ok(self.post('manager','UC03',dict(action='assign',id=task['id'],row_version=task['row_version'],responsible_employee_id=manager['employee_id'],next_contact_at=str(timezone.now()+timedelta(days=1)),reason='主管明确接手原未办事项')))
        self.assertEqual(result['responsible_employee_id'],manager['employee_id']);self.assertIsNone(result['closed_at'])
    def test_zero_fee_requires_physician_signed_basis(self):
        en,n,t,invoice,b=self.signed();b['treatments'][0].update(actual_quantity=0,implementation_result='deferred')
        r=self.ok(self.post('dentist','UC05',b));self.assertEqual(r['billing_state'],'pending_correction');self.assertNotIn('proposed_revision_id',r)
        self.assertEqual(self.post('manager','UC06',dict(action='correct',encounter_id=en['id'],correction_reason='不得代为编写',zero_charge_basis='前台自填')).status_code,422)
        b.update(previous_note_id=r['id'],zero_charge_basis='本次实际未实施项目，经牙医核实不应计费')
        r=self.ok(self.post('dentist','UC05',b));self.assertIn('proposed_revision_id',r)
        approved=self.ok(self.post('manager','UC06',dict(action='correct',encounter_id=en['id'],correction_reason='核实牙医签署零费用依据')))
        self.assertEqual(approved['current_revision']['total_amount'],'0.00');self.assertIn('牙医核实',approved['current_revision']['zero_charge_basis']);self.assertEqual(approved['lines'],[])
    def test_same_idempotency_key_does_not_duplicate_audit_or_revision(self):
        en,n,t,invoice,b=self.signed();key=__import__('uuid').uuid4().hex
        saved=self.ok(self.post('dentist','UC05',b,key));replayed=self.ok(self.post('dentist','UC05',b,key));self.assertTrue(replayed['replayed'])
        self.assertEqual(one('SELECT count(*) n FROM audit_event WHERE request_id=%s',[key])['n'],1)
        self.assertEqual(one('SELECT count(*) n FROM clinical_note WHERE encounter_id=%s',[en['id']])['n'],2)
    def test_prose_only_correction_does_not_stale_confirmed_report(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self)
        report=one('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 1');en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');n=one('SELECT * FROM clinical_note WHERE encounter_id=%s ORDER BY id DESC LIMIT 1',[en['id']]);t=one('SELECT * FROM treatment_revision ORDER BY id DESC LIMIT 1')
        body=dict(action='sign',encounter_id=en['id'],previous_note_id=n['id'],correction_reason='纠正文字不改实施事实',**{k:n[k] for k in NOTE_FIELDS},consent_scope='更正已说明',evidence_reference='核实记录',treatments=[{k:t[k] for k in ['treatment_id','standard_id','actual_quantity','charged_unit_price','implementation_result']}])
        body['aftercare']='补正复诊注意事项';r=self.ok(self.post('dentist','UC05',body));self.assertTrue(r['billing_unchanged']);self.assertEqual(get('quarter_report',report['id'])['confirmation_state'],'confirmed')

    def test_actual_time_correction_preserves_end_and_invalidates_only_relevant_sources(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self)
        en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');a=get('appointment',en['appointment_id']);old=one('SELECT * FROM encounter_revision WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[en['id']])
        r=self.ok(self.post('dentist','UC04',dict(action='correct',appointment_id=a['id'],started_at=str(old['started_at']),reason='核实实际开始时点，结束事实保持')))
        self.assertEqual(r['ended_at'],old['ended_at'].isoformat());self.assertEqual(one('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 1')['confirmation_state'],'stale')
        self.assertEqual(self.post('dentist','UC04',dict(action='correct',appointment_id=a['id'],started_at=str(timezone.now()+timedelta(days=1)),reason='不应允许未来事实')).status_code,422)
    def test_verified_no_show_keeps_actual_reason_and_arrival_is_not_attendance(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));q=one('SELECT * FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[b['starts_at'].date(),b['starts_at'].date()])
        self.assertEqual(self.post('reception','UC04',dict(action='no_show',appointment_id=a['id'],reason='尚未到期不可判断')).status_code,422)
        with patch('core.booking.timezone.now',return_value=b['ends_at']+timedelta(seconds=1)):
            r=self.ok(self.post('reception','UC04',dict(action='no_show',appointment_id=a['id'],reason='电话核实患者未到店')))
            report=operating_report(q)
        self.assertFalse(r['has_attended']);self.assertEqual(report['appointments']['verified_no_shows'],1)
        self.assertTrue(any(x['reason_description']=='电话核实患者未到店' for x in report['appointments']['details']))

if __name__=='__main__':unittest.main(verbosity=2)
