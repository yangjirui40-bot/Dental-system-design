"""Patient miniapp and staff portal use the same original clinical database.
All writes are rolled back in a dedicated synthetic test database.
"""
import json,os,unittest
from django.test import Client
from django.core import signing
import test_integration as base
from core.db import one,get
from core.security import token

class ApplicationSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clients={}
        for role in ['patient','representative','reception','dentist','manager','business','finance','director']:
            surface='patient' if role in ('patient','representative') else 'staff'
            c=Client(HTTP_X_ADC_SURFACE=surface)
            r=c.post('/api/auth/login',data=json.dumps(dict(login_name=role,password=os.environ['DEMO_PASSWORD'],client_surface=surface)),content_type='application/json')
            assert r.status_code==200,r.content
            c.defaults['HTTP_AUTHORIZATION']='Bearer '+r.json()['token'];cls.clients[role]=c
    setUp=base.WorkflowTests.setUp
    rollback=base.WorkflowTests.rollback
    booking=base.WorkflowTests.booking
    post=base.WorkflowTests.post
    def ok(self,r):self.assertEqual(r.status_code,200,r.content);return r.json()
    def login(self,role,surface):
        return Client().post('/api/auth/login',data=json.dumps(dict(login_name=role,password=os.environ['DEMO_PASSWORD'],client_surface=surface)),content_type='application/json')
    def test_patient_login_rejects_all_six_staff_roles(self):
        for role in ['reception','dentist','manager','business','finance','director']:
            self.assertEqual(self.login(role,'patient').status_code,403,role)
    def test_staff_login_rejects_patient_and_representative(self):
        for role in ['patient','representative']:self.assertEqual(self.login(role,'staff').status_code,403)
    def test_unknown_surface_is_not_a_role_escalation(self):
        self.assertEqual(self.login('director','administrator').status_code,422)
    def test_signed_surface_cannot_be_overridden_by_header(self):
        data=self.ok(self.login('patient','patient'))
        c=Client(HTTP_AUTHORIZATION='Bearer '+data['token'],HTTP_X_ADC_SURFACE='staff')
        self.assertEqual(c.get('/api/workspace').status_code,403)
    def test_staff_token_cannot_be_used_as_patient_surface(self):
        data=self.ok(self.login('manager','staff'))
        self.assertEqual(Client(HTTP_AUTHORIZATION='Bearer '+data['token'],HTTP_X_ADC_SURFACE='patient').get('/api/workspace').status_code,403)
    def test_scope_switch_cannot_change_surface(self):
        data=self.ok(self.clients['patient'].get('/api/workspace'))
        r=self.clients['patient'].post('/api/auth/scope',data=json.dumps(dict(scope_id=data['scope']['id'],client_surface='staff')),content_type='application/json')
        self.assertEqual(r.status_code,403)
    def test_patient_cannot_switch_to_employee_scope(self):
        data=self.ok(self.clients['director'].get('/api/workspace'))
        r=self.clients['patient'].post('/api/auth/scope',data=json.dumps(dict(scope_id=data['scope']['id'])),content_type='application/json')
        self.assertEqual(r.status_code,403)
    def test_staff_registration_is_not_available(self):
        r=Client().post('/api/auth/register',data=json.dumps(dict(client_surface='staff',privacy_accepted=True,account_kind='patient')),content_type='application/json')
        self.assertEqual(r.status_code,403)
    def test_patient_workspace_has_no_administrative_resources(self):
        data=self.ok(self.clients['patient'].get('/api/workspace'))
        self.assertEqual(data['application_surface'],'patient')
        for name in ['employees','accounts','scopes','cost_sources','reports','qualifications']:self.assertNotIn(name,data['resources'])
        self.assertEqual({x['code'] for x in data['menu']},{'UC01','UC02','UC03','UC04','UC14'})
    def test_all_seventeen_design_use_cases_remain_covered(self):
        from core.views import DESIGN
        union=set()
        for role,c in self.clients.items():
            ws=self.ok(c.get('/api/workspace'));expected_surface='patient' if role in ('patient','representative') else 'staff'
            self.assertEqual(ws['application_surface'],expected_surface)
            expected={u['id'] for u in DESIGN['cases'] if ws['scope']['role_name'] in u['actors']}
            self.assertEqual({m['code'] for m in ws['menu']},expected,role)
            union.update(expected)
            self.assertTrue(all((s['role_code'] in ('patient','representative'))==(expected_surface=='patient') for s in ws['scopes']))
        self.assertEqual(union,{u['id'] for u in DESIGN['cases']});self.assertEqual(len(union),17)
    def test_patient_booking_appears_in_reception_and_doctor(self):
        body=self.booking();a=self.ok(self.post('patient','UC02',body))
        for role in ['patient','reception','dentist']:
            ws=self.ok(self.clients[role].get('/api/workspace'))
            visible=next(x for x in ws['resources']['appointments'] if x['id']==a['id'])
            self.assertEqual(visible['appointment_no'],a['appointment_no'])
        self.assertEqual(get('appointment',a['id'])['request_channel'],'patient_portal')
    def test_patient_cancellation_is_visible_in_staff_portal(self):
        a=self.ok(self.post('patient','UC02',self.booking()))
        self.ok(self.post('patient','UC03',dict(action='cancel',id=a['id'],row_version=1,reason='本人取消验收')))
        ws=self.ok(self.clients['reception'].get('/api/workspace'))
        self.assertEqual(next(x for x in ws['resources']['appointments'] if x['id']==a['id'])['resolution'],'cancelled')
    def test_patient_arrival_doctor_sign_and_patient_invoice_share_identity(self):
        base.WorkflowTests.test_22_complete_clinical_invoice(self)
        en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');i=one('SELECT * FROM invoice WHERE encounter_id=%s',[en['id']])
        patient=self.ok(self.clients['patient'].get('/api/invoices/'+str(i['id'])))
        self.assertTrue(patient['lines'])
        ws=self.ok(self.clients['reception'].get('/api/workspace'))
        self.assertIn(i['id'],{x['id'] for x in ws['resources']['invoices']})
    def test_patient_cannot_sign_clinical_or_manage_resources(self):
        for code in ['UC05','UC07','UC08','UC09','UC10','UC11','UC12','UC13','UC15','UC16','UC17']:
            self.assertEqual(self.post('patient',code,dict(action='save')).status_code,403,code)
    def test_legacy_staff_wechat_session_is_rejected(self):
        from core.account_access import bind_identity
        import hashlib
        account=one("SELECT * FROM user_account WHERE login_name='dentist'");binding=bind_identity(hashlib.sha256(b'legacy-surface-test').hexdigest(),account)
        scope=one('SELECT id FROM account_scope WHERE account_id=%s AND revoked_at IS NULL',[account['id']])
        raw=signing.dumps({'account':account['id'],'scope':scope['id'],'external_binding':binding['id'],'credential':signing.salted_hmac('adc-credential',account['password_hash']).hexdigest()},salt='adc-wechat-access-v1')
        self.assertEqual(Client(HTTP_AUTHORIZATION='Bearer '+raw).get('/api/workspace').status_code,403)
    def test_original_fifty_eight_business_tables_are_preserved(self):
        self.assertEqual(one("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")['n'],58)

if __name__=='__main__':unittest.main(verbosity=2)
