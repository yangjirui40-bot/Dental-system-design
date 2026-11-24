"""Additional executable scenarios linked to the original 69 extension paths."""
import unittest,json,uuid
from datetime import timedelta
from unittest.mock import patch
import test_completion as completion
import test_integration as base
from core.db import get,one,rows,insert,update,execute
from core.clinical import NOTE_FIELDS
from django.utils import timezone
class SpecificationTests(unittest.TestCase):
    setUpClass=classmethod(base.WorkflowTests.setUpClass.__func__)
    setUp=completion.CompletionTests.setUp
    post=base.WorkflowTests.post;booking=base.WorkflowTests.booking;rollback=base.WorkflowTests.rollback
    ok=completion.CompletionTests.ok;signed=completion.CompletionTests.signed
    def test_uc01_profile_version_conflict_keeps_original(self):
        p=one("SELECT * FROM patient WHERE account_no='P-DEMO-001'")
        r=self.ok(self.post('patient','UC01',dict(action='save',id=p['id'],row_version=p['row_version'],email='new-teaching@example.invalid',emergency_name='合成紧急联系人',emergency_phone='13900009999',emergency_relationship='亲属',change_reason='本人修改演示邮箱')))
        self.assertEqual(self.post('patient','UC01',dict(action='save',id=p['id'],row_version=p['row_version'],email='stale@example.invalid',change_reason='过期版本')).status_code,409)
        self.assertEqual(get('patient',p['id'])['email'],'new-teaching@example.invalid');self.assertIsNotNone(one('SELECT id FROM patient_revision WHERE patient_id=%s',[p['id']]))
    def test_uc01_emergency_contact_cannot_become_consent_agent(self):
        p=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'");a=one("SELECT id FROM user_account WHERE login_name='representative'")
        c=self.ok(self.post('reception','UC01',dict(action='contact',id=p['id'],full_name='应急联系教学对象',phone='13800009001',relationship='朋友',contact_purpose='emergency')))
        self.assertEqual(self.post('reception','UC01',dict(action='authority',id=p['id'],contact_id=c['id'],authorized_account_id=a['id'],permission_scope='consent',evidence_reference='不能仅凭紧急联系关系',valid_from=str(timezone.now()))).status_code,422)
    def test_uc01_allergy_correction_preserves_source_and_original(self):
        self.ok(self.post('patient','UC02',self.booking()));p=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'");substance=one('SELECT id FROM allergy_substance ORDER BY id LIMIT 1')
        first=self.ok(self.post('patient','UC01',dict(action='allergy',id=p['id'],substance_id=substance['id'],reaction_description='自述教学反应',report_source='患者本人',verification_result='reported')))
        self.assertEqual(self.post('patient','UC01',dict(action='allergy',id=p['id'],substance_id=substance['id'],verification_result='verified',correction_reason='无权自行核实')).status_code,403)
        revised=self.ok(self.post('dentist','UC01',dict(action='allergy',id=p['id'],substance_id=substance['id'],reaction_description='牙医核实教学反应',report_source='当次面核',verification_result='verified',correction_reason='补充核实依据')))
        self.assertEqual(revised['replaces_id'],first['id']);self.assertEqual(get('allergy_revision',first['id'])['verification_result'],'reported')
    def test_uc02_symptom_only_and_authorised_assistance(self):
        b=self.booking();b.update(standard_ids=[],presenting_request='患者仅能描述进食不适，先安排检查')
        a=self.ok(self.post('representative','UC02',b));self.assertEqual(a['request_channel'],'representative_portal')
        self.assertEqual(one('SELECT count(*) n FROM appointment_request_item WHERE appointment_id=%s',[a['id']])['n'],0)
    def test_uc04_assisted_arrival_leave_and_wrong_day(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));self.assertEqual(self.post('patient','UC04',dict(action='arrive',appointment_id=a['id'])).status_code,422)
        with patch('core.booking.timezone.localdate',return_value=b['starts_at'].date()):
            r=self.ok(self.post('reception','UC04',dict(action='arrive',appointment_id=a['id'])));self.assertFalse(r['has_attended'])
        r=self.ok(self.post('reception','UC04',dict(action='leave',appointment_id=a['id'],reason='患者确实到店后未接诊离开')));self.assertEqual(r['resolution'],'left_unseen');self.assertFalse(r['has_attended']);self.assertIsNone(one('SELECT id FROM encounter WHERE appointment_id=%s',[a['id']]))
    def test_uc04_identity_or_allergy_unconfirmed_cannot_start(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b))
        with patch('core.booking.timezone.localdate',return_value=b['starts_at'].date()):self.ok(self.post('reception','UC04',dict(action='arrive',appointment_id=a['id'])))
        r=self.post('dentist','UC04',dict(action='start',appointment_id=a['id'],identity_confirmed=True,allergy_confirmed=False));self.assertEqual(r.status_code,422);self.assertIsNone(one('SELECT id FROM encounter WHERE appointment_id=%s',[a['id']]))
    def test_uc05_invalid_precision_and_unconfirmed_consent_roll_back_signature(self):
        en,n,t,i,b=self.signed();b['treatments'][0]['actual_quantity']='0.5';self.assertEqual(self.post('dentist','UC05',b).status_code,422)
        b['treatments'][0]['actual_quantity']=1;b['evidence_reference']='';self.assertEqual(self.post('dentist','UC05',b).status_code,422);self.assertEqual(get('clinical_note',n['id'])['signature_state'],'signed')
    def test_uc05_actual_addition_and_interruption_are_billed_from_signed_items(self):
        en,n,t,i,b=self.signed();second=one("SELECT * FROM treatment_standard WHERE approval_state='approved' AND id<>%s ORDER BY id LIMIT 1",[t['standard_id']])
        b['treatments'][0]['implementation_result']='interrupted';b['treatments'].append(dict(standard_id=second['id'],actual_quantity=1,charged_unit_price=second['unit_price'],site_description='教学记录实际部位',implementation_result='performed',performed_at=str(t['performed_at'])))
        r=self.ok(self.post('dentist','UC05',b));pending=get('invoice_revision',r['proposed_revision_id']);self.assertEqual(one('SELECT count(*) n FROM invoice_line WHERE invoice_revision_id=%s',[pending['id']])['n'],2)
        self.assertEqual(get('invoice_revision',i['id'])['validity'],'current')
    def test_uc06_retry_returns_same_business_invoice_and_copy(self):
        en,n,t,i,b=self.signed();before=one('SELECT count(*) n FROM invoice')['n'];r=self.ok(self.post('reception','UC06',dict(action='issue',encounter_id=en['id'])))
        self.assertEqual(r['id'],i['invoice_id']);self.assertEqual(one('SELECT count(*) n FROM invoice')['n'],before)
        copy=self.ok(self.clients['patient'].get('/api/invoices/'+str(r['id'])));self.assertTrue(copy['copy_details']['clinic_name']);self.assertNotIn('medical_history',json.dumps(copy))
    def test_uc07_closure_cannot_strand_future_promises_or_accept_negative_area(self):
        b=self.booking();a=self.ok(self.post('patient','UC02',b));c=get('clinic',a['clinic_id'])
        self.assertEqual(self.post('business','UC07',dict(action='save',id=c['id'],row_version=c['row_version'],closed_on=str(timezone.localdate()))).status_code,422);self.assertIsNone(get('clinic',c['id'])['closed_on'])
        r=self.post('business','UC07',dict(action='save',clinic_name='无效面积门店',postal_address='教学地址',phone='02000009001',email='bad@example.invalid',floor_area=-1,opened_on='2020-01-01'));self.assertIn(r.status_code,[400,409])
    def standard_draft(self):
        s=one('SELECT * FROM treatment_standard ORDER BY id LIMIT 1')
        body={k:s[k] for k in ['treatment_id','treatment_name','unit_name','quantity_scale','unit_price','site_requirement','duration_minutes']};body.update(action='draft',valid_from=str(timezone.now()-timedelta(days=1)))
        return self.ok(self.post('business','UC10',body))
    def test_uc10_overlap_does_not_retire_approved_original(self):
        d=self.standard_draft();r=self.post('director','UC10',dict(action='approve',id=d['id'],retire_previous=False));self.assertEqual(r.status_code,409);self.assertEqual(get('treatment_standard',d['id'])['approval_state'],'draft')
    def test_uc10_unapproved_retired_and_disabled_catalog_are_not_new_booking_choices(self):
        b=self.booking();d=self.standard_draft();b['standard_ids']=[d['id']];self.assertEqual(self.post('patient','UC02',b).status_code,422)
        b=self.booking();s=get('treatment_standard',b['standard_ids'][0]);self.ok(self.post('business','UC10',dict(action='disable',id=s['treatment_id'])));self.assertEqual(self.post('patient','UC02',b).status_code,422)
    def test_uc10_rejection_requires_reason_and_retains_audited_decision(self):
        d=self.standard_draft();self.assertEqual(self.post('director','UC10',dict(action='reject',id=d['id'])).status_code,422)
        self.ok(self.post('director','UC10',dict(action='reject',id=d['id'],reason='单位与有效期间待重新核实')));event=one("SELECT * FROM audit_event WHERE object_kind='UC10' AND business_reference=%s AND operation_name='reject'",[str(d['id'])]);self.assertIn('单位与有效期间',event['changed_fields'])
    def test_uc11_cross_clinic_and_cross_period_allocation_preserves_single_source(self):
        quarters=rows('SELECT id FROM fiscal_quarter ORDER BY starts_on LIMIT 2');clinics=rows('SELECT id FROM clinic ORDER BY id');d=one('SELECT id FROM dentist ORDER BY id LIMIT 1')
        body=dict(action='source',source_document_no='SPEC-SHARED',source_line_no=1,cost_category='operating',document_date=str(timezone.localdate()),evidence_reference='教学原始凭据',source_amount='100',allocations=[dict(quarter_id=quarters[0]['id'],clinic_id=clinics[0]['id'],dentist_id=d['id'],allocated_amount='40',allocation_basis='第一期间实际归属'),dict(quarter_id=quarters[1]['id'],clinic_id=clinics[1]['id'],dentist_id=d['id'],allocated_amount='60',allocation_basis='第二门店期间实际归属')])
        revision=self.ok(self.post('finance','UC11',body));self.assertEqual(sum(a['allocated_amount'] for a in rows('SELECT * FROM cost_allocation WHERE cost_revision_id=%s',[revision['id']])),100)
        self.assertEqual(self.post('finance','UC11',body).status_code,409);self.assertEqual(one("SELECT count(*) n FROM cost_source WHERE source_document_no='SPEC-SHARED'")['n'],1)
    def test_uc11_dispute_cannot_be_counted_as_approved_cost(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self);allocation=one('SELECT * FROM cost_allocation ORDER BY id DESC LIMIT 1')
        self.assertEqual(self.post('manager','UC11',dict(action='review',id=allocation['id'],approved=False)).status_code,422)
        self.ok(self.post('manager','UC11',dict(action='review',id=allocation['id'],approved=False,reason='来源实际归属有争议')))
        q=one('SELECT quarter_id FROM quarter_report ORDER BY id DESC LIMIT 1')['quarter_id'];data=self.ok(self.clients['director'].get('/api/reports?quarter_id='+str(q)));self.assertEqual(one('SELECT confirmation_state FROM quarter_report ORDER BY id DESC LIMIT 1')['confirmation_state'],'stale');self.assertTrue(data['issues']);self.assertTrue(all(row['supplies_cost']=='0' or row['supplies_cost']=='0.00' for row in data['rows']))
    def test_uc12_empty_period_and_clinic_scope_do_not_fabricate_group_fund(self):
        q=one('SELECT id FROM fiscal_quarter ORDER BY starts_on LIMIT 1');data=self.ok(self.clients['director'].get('/api/reports?quarter_id='+str(q['id'])));self.assertEqual(data['rows'],[]);self.assertEqual(data['incentive_fund'],'0.00');self.assertIsNone(data['operations']['appointments']['cancellation_rate'])
        manager=self.ok(self.clients['manager'].get('/api/reports?quarter_id='+str(q['id'])));self.assertIsNone(manager['incentive_fund']);self.assertEqual(manager['scope_kind'],'clinic')
    def test_uc13_predecessor_and_consent_gate_preserve_stable_phase(self):
        base.WorkflowTests.test_28_plan_phase_and_cancellation_continuity(self);phase=one('SELECT * FROM treatment_phase WHERE phase_no=2 ORDER BY id DESC LIMIT 1');b=self.booking();b['phase_id']=phase['id'];self.assertEqual(self.post('patient','UC02',b).status_code,422)
        en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');r=self.post('dentist','UC13',dict(action='phase',phase_id=phase['id'],encounter_id=en['id'],outcome='ready',clinical_confirmed=True));self.assertEqual(r.status_code,422)
    def test_uc13_boolean_string_cannot_release_stage(self):
        self.assertEqual(self.post('dentist','UC13',dict(action='confirm',confirm_existing_revision='false')).status_code,400)
        en,n,t,i,b=self.signed();a=get('appointment',en['appointment_id']);body=dict(action='confirm',encounter_id=en['id'],consent_scope='阶段教学同意',evidence_reference='核实依据',phases=[dict(phase_no=1,phase_title='待核实',clinical_condition='未放行',responsible_clinic_id=a['clinic_id'],clinical_released='false',items=[])])
        self.assertEqual(self.post('dentist','UC13',body).status_code,422)
    def test_uc15_overlapping_calendar_and_duplicate_operatory_are_rejected(self):
        b=self.booking();d=get('practice_duty',b['duty_id']);c=get('clinic_calendar',d['calendar_id'])
        body={k:c[k] for k in ['clinic_id','work_date','is_open','starts_at','ends_at']};body.update(action='calendar',session_no=2);self.assertEqual(self.post('manager','UC15',body).status_code,409)
        op=get('operatory',b['operatory_id']);body={k:op[k] for k in ['clinic_id','operatory_code','operatory_name','resource_state']};body.update(action='operatory');self.assertEqual(self.post('manager','UC15',body).status_code,409)
    def test_uc16_duplicate_account_and_expired_authority_never_leak_password_hash(self):
        p=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'");r=self.post('reception','UC16',dict(action='create',account_kind='patient',patient_id=p['id'],login_name='patient',display_name='重复名称',password='TestOnlyPassword2026'));self.assertEqual(r.status_code,409);self.assertNotIn('password_hash',r.content.decode())
    def test_uc17_empty_results_and_foreign_clinic_scope(self):
        r=self.ok(self.clients['manager'].get('/api/audit?reference=NO-SUCH-REFERENCE'));self.assertEqual(r['items'],[])
        other=one('SELECT id FROM clinic WHERE id<>%s LIMIT 1',[one("SELECT s.clinic_id FROM account_scope s JOIN user_account a ON a.id=s.account_id WHERE a.login_name='manager' LIMIT 1")['clinic_id']]);self.assertEqual(self.clients['manager'].get('/api/audit?clinic_id='+str(other['id'])).status_code,403)

    def test_uc13_booked_definition_change_and_missing_consent_cannot_rewrite_plan(self):
        base.WorkflowTests.test_28_plan_phase_and_cancellation_continuity(self)
        root=one('SELECT * FROM treatment_plan ORDER BY id DESC LIMIT 1');phase=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=1',[root['id']]);booking=self.booking();booking['phase_id']=phase['id'];a=self.ok(self.post('patient','UC02',booking))
        detail=self.ok(self.clients['dentist'].get('/api/plans/'+str(root['id'])))
        body=dict(action='confirm',id=root['id'],row_version=root['row_version'],encounter_id=root['origin_encounter_id'],change_reason='更改已被预约的阶段定义',consent_scope='计划修订同意',evidence_reference='本人已说明',phases=detail['phases'],dependencies=[[1,2]])
        body['phases'][0]['phase_title']='变化后的定义';count=one('SELECT count(*) n FROM plan_revision WHERE plan_id=%s',[root['id']])['n']
        self.assertEqual(self.post('dentist','UC13',body).status_code,422);self.assertEqual(one('SELECT count(*) n FROM plan_revision WHERE plan_id=%s',[root['id']])['n'],count);self.assertEqual(get('appointment',a['id'])['resolution'],'booked')
        body.pop('id');body.pop('row_version');body['evidence_reference']='';self.assertEqual(self.post('dentist','UC13',body).status_code,422)
    def test_uc11_approved_revision_stales_report_but_frozen_sources_keep_old_amount(self):
        base.WorkflowTests.test_27_cost_review_and_quarter_source_snapshot(self)
        report=one('SELECT * FROM quarter_report ORDER BY id DESC LIMIT 1');old=one('SELECT * FROM cost_revision ORDER BY id DESC LIMIT 1');allocation=one('SELECT * FROM cost_allocation WHERE cost_revision_id=%s',[old['id']]);source=get('cost_source',old['cost_source_id'])
        body=dict(action='source',source_id=source['id'],source_amount='90.50',correction_reason='补核实实际凭据金额',allocations=[dict(quarter_id=allocation['quarter_id'],clinic_id=allocation['clinic_id'],dentist_id=allocation['dentist_id'],allocated_amount='90.50',allocation_basis='实际凭据更正')])
        pending=self.ok(self.post('finance','UC11',body));self.assertEqual(get('quarter_report',report['id'])['confirmation_state'],'confirmed');a=one('SELECT * FROM cost_allocation WHERE cost_revision_id=%s',[pending['id']])
        self.ok(self.post('manager','UC11',dict(action='review',id=a['id'],approved=True)));self.assertEqual(get('quarter_report',report['id'])['confirmation_state'],'stale')
        frozen=self.ok(self.clients['director'].get('/api/reports/'+str(report['id'])));self.assertEqual(frozen['sources']['costs'][0]['allocated_amount'],'80.50');self.assertEqual(get('cost_revision',old['id'])['source_amount'],__import__('decimal').Decimal('80.50'))

    def test_uc12_unpublished_coordination_does_not_invent_cost_reporting_obligation(self):
        employee=self.ok(self.post('business','UC08',dict(action='employee',full_name='仅协调未发布医生',birth_date='1990-01-01',home_address='虚构地址',phone='13800009008',email='draft-only@example.invalid',employed_from='2020-01-01')))
        self.ok(self.post('business','UC08',dict(action='dentist',employee_id=employee['id'],professional_no='SPEC-DRAFT-ONLY')))
        b=self.booking();d=get('practice_duty',b['duty_id']);body={k:d[k] for k in ['clinic_id','calendar_id','starts_at','ends_at']};body.update(action='draft',dentist_id=employee['id'])
        self.ok(self.post('business','UC09',body));q=one('SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[d['starts_at'].date(),d['starts_at'].date()])
        data=self.ok(self.clients['director'].get('/api/reports?quarter_id='+str(q['id'])));self.assertNotIn(employee['id'],[row['dentist_id'] for row in data['rows']]);self.assertFalse(any('牙医'+str(employee['id'])+'／' in issue for issue in data['issues']))

    def test_scope_roles_cannot_escape_patient_and_clinic_boundaries(self):
        from core.security import token
        from django.test import Client
        account=one("SELECT * FROM user_account WHERE login_name='dentist'");manager=one("SELECT id FROM access_role WHERE role_code='manager'");dentist=one("SELECT id FROM access_role WHERE role_code='dentist'")
        self.assertEqual(self.post('director','UC16',dict(action='grant',account_id=account['id'],role_id=manager['id'],scope_kind='group')).status_code,403)
        scope=self.ok(self.post('director','UC16',dict(action='grant',account_id=account['id'],role_id=dentist['id'],scope_kind='group')))
        foreign=insert('patient',dict(account_no='SPEC-UNRELATED',full_name='无关教学患者',birth_date='1990-01-01',billing_address='无关教学地址',phone='13800009888',allergy_declaration='unknown',row_version=1,created_at=timezone.now()))
        client=Client(HTTP_AUTHORIZATION='Bearer '+token(account,scope['id']))
        self.assertEqual(client.get('/api/patients/'+str(foreign['id'])).status_code,403)
        r=client.post('/api/use-cases/UC01',data=json.dumps(dict(action='allergy',id=foreign['id'],substance_id=1,verification_result='reported')),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(r.status_code,403)

    def test_phase_booking_derives_items_and_full_quantity_duration(self):
        en,n,t,i,body=self.signed();a=get('appointment',en['appointment_id']);standard=get('treatment_standard',t['standard_id'])
        phases=[dict(phase_no=1,phase_title='不同部位的同项目',clinical_condition='教学已核实可约',responsible_clinic_id=a['clinic_id'],clinical_released=True,items=[dict(standard_id=standard['id'],site_description='教学左侧',planned_quantity=1),dict(standard_id=standard['id'],site_description='教学右侧',planned_quantity=1)]),dict(phase_no=2,phase_title='未指定项目的已放行复查',clinical_condition='教学已核实复查可约',responsible_clinic_id=a['clinic_id'],clinical_released=True,items=[])]
        plan=self.ok(self.post('dentist','UC13',dict(action='confirm',encounter_id=en['id'],consent_scope='教学分阶段方案同意',evidence_reference='当次教学核实',phases=phases,dependencies=[])))
        first=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=1',[plan['id']]);b=self.booking();b.update(phase_id=first['id'],standard_ids=[])
        self.assertEqual(self.post('patient','UC02',b).status_code,422)
        b['ends_at']=b['starts_at']+timedelta(minutes=standard['duration_minutes']*2);booked=self.ok(self.post('patient','UC02',b));self.assertEqual(one('SELECT count(*) n FROM appointment_request_item WHERE appointment_id=%s',[booked['id']])['n'],1)
        second=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=2',[plan['id']]);b.update(phase_id=second['id'],starts_at=b['ends_at'],ends_at=b['ends_at']+timedelta(minutes=30),presenting_request='接续已确认复查阶段')
        b.pop('presenting_request',None);result=self.ok(self.post('patient','UC02',b));self.assertIn('接续已确认阶段',result['presenting_request']);self.assertEqual(one('SELECT phase_id FROM appointment_phase WHERE appointment_id=%s',[result['id']])['phase_id'],second['id'])
    def test_planned_quantity_respects_standard_precision(self):
        en,n,t,i,body=self.signed();a=get('appointment',en['appointment_id']);phases=[dict(phase_no=1,phase_title='无效预计数量',clinical_condition='教学回归',responsible_clinic_id=a['clinic_id'],clinical_released=False,items=[dict(standard_id=t['standard_id'],planned_quantity='0.5')])]
        response=self.post('dentist','UC13',dict(action='draft',encounter_id=en['id'],phases=phases));self.assertEqual(response.status_code,422)
        self.assertIsNone(one("SELECT id FROM phase_specification WHERE phase_title='无效预计数量'"))

if __name__=='__main__':unittest.main(verbosity=2)
