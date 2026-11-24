"""Design-to-window regressions against a real isolated PostgreSQL database."""
import json,uuid,unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import test_integration as base
from core.db import get,one,rows,insert,execute
from django.utils import timezone

class BusinessWindowTests(unittest.TestCase):
    setUpClass=classmethod(base.WorkflowTests.setUpClass.__func__)
    setUp=base.WorkflowTests.setUp
    rollback=base.WorkflowTests.rollback
    post=base.WorkflowTests.post
    booking=base.WorkflowTests.booking
    def ok(self,response):
        self.assertEqual(response.status_code,200,response.content);return response.json()
    def patient(self):return one("SELECT * FROM patient WHERE account_no='P-DEMO-001'")
    def profile(self,**changes):return dict(action='save',id=self.patient()['id'],row_version=self.patient()['row_version'],change_reason='核实本人登记资料',**changes)
    def register(self,**changes):
        data=dict(account_kind='patient',full_name='新建资料测试 '+uuid.uuid4().hex[:8],birth_date='2000-01-01',phone='139'+str(uuid.uuid4().int)[:8],billing_address='合成地址',login_name='window_'+uuid.uuid4().hex[:12],password='OnlyTest!Account2026',privacy_accepted=True,emergency_name='合成亲属',emergency_phone='13900009999',emergency_relationship='亲属');data.update(changes)
        return self.clients['patient'].post('/api/auth/register',data=json.dumps(data),content_type='application/json'),data
    def query(self,resource='appointments',role='patient',**params):return self.clients[role].get('/api/records',dict(resource=resource,**params))
    def appointment(self,at,patient_id=None):
        b=self.booking();b.pop('action');b.pop('standard_ids');b.update(patient_id=patient_id or b['patient_id'],starts_at=at,ends_at=at+timedelta(minutes=20))
        return insert('appointment',dict(**b,appointment_no='Q-'+uuid.uuid4().hex,resolution='cancelled',created_at=timezone.now(),row_version=1,request_channel='patient_portal',created_account_id=one("SELECT id FROM user_account WHERE login_name='patient'")['id']))
    def guardian(self,purpose='guardian'):
        return insert('patient_contact',dict(patient_id=self.patient()['id'],full_name='合成监护人',phone='13900008888',relationship='监护人',contact_purpose=purpose,recorded_account_id=one("SELECT id FROM user_account WHERE login_name='reception'")['id'],recorded_at=timezone.now()))
    def authority(self,contact,**changes):
        b=dict(action='authority',id=self.patient()['id'],contact_id=contact['id'],permission_scope='consent',evidence_reference='现场核实的合成监护依据',valid_from=(timezone.now()-timedelta(days=1)).isoformat());b.update(changes);return self.post('reception','UC01',b)
    def test_profile_requires_emergency_and_rolls_back_all_changes(self):
        p=self.patient();execute("DELETE FROM patient_contact WHERE patient_id=%s AND contact_purpose='emergency'",[p['id']]);before=one('SELECT count(*) AS n FROM patient_revision')['n']
        self.assertEqual(self.post('patient','UC01',self.profile(full_name='不得持久化的修改')).status_code,422)
        self.assertEqual(get('patient',p['id']),p);self.assertEqual(one('SELECT count(*) AS n FROM patient_revision')['n'],before)
    def test_contact_append_preserves_old_evidence_and_repeated_save_does_not_duplicate(self):
        p=self.patient();contact=dict(emergency_name='新紧急联系人',emergency_phone='13900007777',emergency_relationship='亲属')
        self.ok(self.post('patient','UC01',self.profile(**contact)));latest=one("SELECT * FROM patient_contact WHERE patient_id=%s AND contact_purpose='emergency' ORDER BY id DESC LIMIT 1",[p['id']]);self.assertEqual(latest['full_name'],contact['emergency_name'])
        before=one('SELECT count(*) AS n FROM patient_contact')['n'];self.ok(self.post('patient','UC01',self.profile(**contact)));self.assertEqual(one('SELECT count(*) AS n FROM patient_contact')['n'],before)
        self.assertEqual(one('SELECT full_name FROM patient_revision WHERE patient_id=%s ORDER BY revision_no DESC LIMIT 1',[p['id']])['full_name'],p['full_name'])
    def test_allergy_summary_cannot_erase_unresolved_item(self):
        self.ok(self.post('patient','UC01',dict(action='allergy',id=self.patient()['id'],substance_id=one('SELECT id FROM allergy_substance LIMIT 1')['id'],reaction_description='合成申报反应',report_source='本人申报',verification_result='reported')))
        self.assertTrue(one('SELECT id FROM patient_allergy WHERE patient_id=%s',[self.patient()['id']]))
        self.assertEqual(self.post('patient','UC01',self.profile(allergy_declaration='denied')).status_code,422)
        self.assertEqual(self.post('patient','UC01',self.profile(allergy_declaration='unknown')).status_code,422)
    def test_reported_summary_requires_real_item(self):
        p=self.patient();execute('DELETE FROM allergy_revision WHERE allergy_id IN (SELECT id FROM patient_allergy WHERE patient_id=%s)',[p['id']]);execute('DELETE FROM patient_allergy WHERE patient_id=%s',[p['id']]);self.assertEqual(self.post('patient','UC01',self.profile(allergy_declaration='reported')).status_code,422)
    def test_registration_requires_emergency_before_creating_identity(self):
        before=one('SELECT count(*) AS n FROM patient')['n'];response,b=self.register(emergency_name='',emergency_phone='',emergency_relationship='');self.assertEqual(response.status_code,422);self.assertIsNone(one('SELECT id FROM user_account WHERE login_name=%s',[b['login_name']]));self.assertEqual(one('SELECT count(*) AS n FROM patient')['n'],before)
    def test_registration_saves_contact_initial_revision_and_patient_reported_allergy(self):
        substance=one('SELECT id FROM allergy_substance LIMIT 1');response,b=self.register(allergy_declaration='reported',allergy_substance_id=substance['id'],allergy_reaction='合成申报反应');self.ok(response);account=one('SELECT * FROM user_account WHERE login_name=%s',[b['login_name']]);pid=account['patient_id'];self.assertEqual(get('patient',pid)['allergy_declaration'],'reported')
        self.assertEqual(one('SELECT recorded_account_id FROM patient_revision WHERE patient_id=%s',[pid])['recorded_account_id'],account['id']);self.assertEqual(one('SELECT contact_purpose FROM patient_contact WHERE patient_id=%s',[pid])['contact_purpose'],'emergency')
        item=one('SELECT r.* FROM allergy_revision r JOIN patient_allergy a ON a.id=r.allergy_id WHERE a.patient_id=%s',[pid]);self.assertEqual(item['verification_result'],'reported');self.assertIsNone(item['verified_by']);self.assertEqual(item['recorded_account_id'],account['id'])
    def test_registration_rejects_reported_without_item_and_bad_state(self):
        for changes in [dict(allergy_declaration='reported'),dict(allergy_declaration='verified'),dict(allergy_declaration='reported',allergy_substance_id=999999,allergy_reaction='测试')]:self.assertEqual(self.register(**changes)[0].status_code,422)
    def test_negative_allergy_declaration_is_not_a_fake_substance(self):
        response,b=self.register(allergy_declaration='denied');self.ok(response);p=one('SELECT p.* FROM patient p JOIN user_account a ON a.patient_id=p.id WHERE a.login_name=%s',[b['login_name']]);self.assertEqual(p['allergy_declaration'],'denied');self.assertIsNone(one('SELECT id FROM patient_allergy WHERE patient_id=%s',[p['id']]))
    def test_offline_guardian_authority_needs_no_online_account(self):
        scopes=one('SELECT count(*) AS n FROM account_scope')['n'];authority=self.ok(self.authority(self.guardian()));self.assertIsNone(authority['authorized_account_id']);self.assertEqual(one('SELECT count(*) AS n FROM account_scope')['n'],scopes)
    def test_emergency_contact_is_not_clinical_consent(self):self.assertEqual(self.authority(self.guardian('emergency')).status_code,422)
    def test_online_authority_rejects_employee_and_bad_interval(self):
        c=self.guardian();account=one("SELECT id FROM user_account WHERE login_name='dentist'");self.assertEqual(self.authority(c,authorized_account_id=account['id']).status_code,422);self.assertEqual(self.authority(c,permission_scope='invented').status_code,422);self.assertEqual(self.authority(c,valid_to=(timezone.now()-timedelta(days=2)).isoformat()).status_code,422)
    def test_date_range_includes_whole_last_day_and_uses_shanghai(self):
        start=datetime(2030,1,5,tzinfo=ZoneInfo('Asia/Shanghai'));inside=[self.appointment(start),self.appointment(start+timedelta(hours=23,minutes=59))];outside=[self.appointment(start-timedelta(minutes=1)),self.appointment(start+timedelta(days=1))];result=self.ok(self.query(from_date='2030-01-05',to_date='2030-01-05'));ids={a['id'] for a in result['items']};self.assertTrue({a['id'] for a in inside}<=ids);self.assertFalse({a['id'] for a in outside}&ids)
    def test_date_query_preserves_patient_scope_and_does_not_write(self):
        start=datetime(2030,1,5,tzinfo=ZoneInfo('Asia/Shanghai'));other=insert('patient',dict(account_no='OTHER-'+uuid.uuid4().hex,full_name='其他合成患者',birth_date='2000-01-01',billing_address='合成',phone='13900000000',allergy_declaration='unknown',row_version=1,created_at=timezone.now()));hidden=self.appointment(start,other['id']);before=one('SELECT count(*) AS n FROM audit_event')['n'];result=self.ok(self.query(from_date='2030-01-05',to_date='2030-01-05',patient_id=other['id']));self.assertNotIn(hidden['id'],{a['id'] for a in result['items']});self.assertEqual(one('SELECT count(*) AS n FROM audit_event')['n'],before)
    def test_invalid_and_reversed_ranges_fail_explicitly(self):
        for params in [dict(from_date='bad'),dict(to_date='2030-02-30'),dict(from_date='2030-02-02',to_date='2030-02-01')]:self.assertEqual(self.query(**params).status_code,422)
    def test_cursor_keeps_date_range_without_gaps_or_duplicates(self):
        at=datetime(2030,2,1,tzinfo=ZoneInfo('Asia/Shanghai'));created={self.appointment(at+timedelta(minutes=i))['id'] for i in range(205)};first=self.ok(self.query(from_date='2030-02-01',to_date='2030-02-01'));self.assertEqual(len(first['items']),200);second=self.ok(self.query(from_date='2030-02-01',to_date='2030-02-01',before=first['next']));self.assertEqual(len(second['items']),5);self.assertIsNone(second['next']);self.assertEqual({a['id'] for a in first['items']+second['items']},created)
    def test_invoice_range_uses_current_revision_issue_date(self):
        base.WorkflowTests.test_22_complete_clinical_invoice(self);item=one("SELECT * FROM invoice_revision WHERE validity='current' ORDER BY id DESC LIMIT 1");execute("UPDATE invoice_revision SET issued_at='2030-04-02T23:59:00+08:00' WHERE id=%s",[item['id']]);included=self.ok(self.query(resource='invoices',from_date='2030-04-02',to_date='2030-04-02'));excluded=self.ok(self.query(resource='invoices',from_date='2030-04-03',to_date='2030-04-03'));self.assertIn(item['invoice_id'],{i['id'] for i in included['items']});self.assertNotIn(item['invoice_id'],{i['id'] for i in excluded['items']});self.assertTrue(all(i['clinic_name'] for i in included['items']))
    def test_profile_history_is_paginated_and_preserves_actual_actor(self):
        p=self.patient();account=one("SELECT id FROM user_account WHERE login_name='patient'")
        for number in range(51):insert('patient_revision',dict(**{k:p[k] for k in ['full_name','birth_date','sex_code','billing_address','phone','email']},patient_id=p['id'],revision_no=1000+number,change_reason='合成历史分页核查',recorded_account_id=account['id'],recorded_at=timezone.now()))
        path='/api/patients/'+str(p['id']);first=self.ok(self.clients['patient'].get(path,dict(history_kind='profile')));self.assertEqual(len(first['items']),50);self.assertTrue(all(r['recorded_account_id']==account['id'] and r['recorded_name'] for r in first['items']));second=self.ok(self.clients['patient'].get(path,dict(history_kind='profile',history_before=first['next'])));self.assertFalse({i['id'] for i in first['items']}&{i['id'] for i in second['items']});self.assertIsNone(second['next'])
    def test_allergy_history_retains_prior_report_and_is_not_public_or_finance_visible(self):
        pid=self.patient()['id'];substance=one('SELECT id FROM allergy_substance LIMIT 1');first=self.ok(self.post('patient','UC01',dict(action='allergy',id=pid,substance_id=substance['id'],reaction_description='原始合成申报',report_source='本人',verification_result='reported')))
        self.ok(self.post('patient','UC01',dict(action='allergy',id=pid,substance_id=substance['id'],reaction_description='补充合成申报',report_source='本人补充',verification_result='reported',correction_reason='补充反应说明')))
        path='/api/patients/'+str(pid);result=self.ok(self.clients['patient'].get(path));history=result['allergy_history']['items'];self.assertTrue(any(i['id']==first['id'] and i['reaction_description']=='原始合成申报' for i in history));self.assertEqual(self.clients['finance'].get(path,dict(history_kind='allergy')).status_code,403);self.assertEqual(self.clients['patient'].get(path,dict(history_kind='invented')).status_code,422)

if __name__=='__main__':unittest.main(verbosity=2)
