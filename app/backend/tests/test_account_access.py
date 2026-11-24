"""Real isolated PostgreSQL account security tests; WeChat provider replies mocked explicitly."""
import os,json,uuid,unittest,hashlib,time,io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier,Event
from pathlib import Path
from unittest.mock import patch,MagicMock
import test_integration as base
from django.test import Client,override_settings
from django.db import transaction,connection
from django.conf import settings
from django.core import signing
from core.db import one,rows,execute,get
from core.account_access import choice,bind_identity,IDENTITY_SALT,insert as original_insert

class AccountAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execute((settings.CONTRACTS_DIR/'auth-001.sql').read_text())
        base.WorkflowTests.setUpClass.__func__(cls)
    def setUp(self):
        self.tx=transaction.atomic();self.tx.__enter__();self.addCleanup(self.rollback)
        self.client=Client();self.subject=hashlib.sha256(('test-wechat-'+uuid.uuid4().hex).encode()).hexdigest()
        self.setting=override_settings(WECHAT_APP_SECRET='mock-only-not-a-real-platform-secret');self.setting.enable();self.addCleanup(self.setting.disable)
    rollback=base.WorkflowTests.rollback
    def post(self,path,b):return self.client.post('/api/auth/'+path,data=json.dumps(b),content_type='application/json')
    def ok(self,r):self.assertEqual(r.status_code,200,r.content);return r.json()
    def proof(self):return choice(self.subject)['identity_ticket']
    def account(self,role='patient'):return one('SELECT * FROM user_account WHERE login_name=%s',[role])
    def mapped(self,role='patient'):
        account=self.account(role);bind_identity(self.subject,account);return account
    def registration(self,**overrides):
        body=dict(account_kind='patient',full_name='账号测试患者',birth_date='2000-01-01',phone='139'+str(uuid.uuid4().int)[:8],billing_address='合成地址',emergency_name='合成紧急联系人',emergency_phone='13900009999',emergency_relationship='亲属',login_name='auth_'+uuid.uuid4().hex[:16],password='OnlyTest!Account2026',privacy_accepted=True);body.update(overrides);return body
    def test_unconfigured_wechat_preserves_password_login(self):
        with override_settings(WECHAT_APP_SECRET=''):
            self.assertFalse(self.ok(self.client.get('/api/auth/options'))['wechat_enabled'])
            self.assertEqual(self.post('wechat',dict(code='valid-looking-code',privacy_accepted=True)).status_code,503)
            self.assertEqual(self.post('login',dict(login_name='patient',password=os.environ['DEMO_PASSWORD'])).status_code,200)
    def test_provider_code_required_not_frontend_openid(self):
        with patch('core.account_access.urlopen') as provider:
            self.assertEqual(self.post('wechat',dict(openid='forged-client-id',privacy_accepted=True)).status_code,401);provider.assert_not_called()
    def test_provider_exchange_does_not_leak_secret_or_session_key(self):
        reply=MagicMock();reply.__enter__.return_value=io.StringIO(json.dumps({'openid':'provider-verified-subject','session_key':'must-never-reach-client'}))
        with patch('core.account_access.urlopen',return_value=reply) as provider:
            r=self.post('wechat',dict(code='real-flow-code',privacy_accepted=True));data=self.ok(r)
        self.assertEqual(data['state'],'register_or_bind');self.assertNotIn('provider-verified-subject',r.content.decode());self.assertNotIn('must-never-reach-client',r.content.decode());self.assertNotIn(settings.WECHAT_APP_SECRET,r.content.decode())
        payload=signing.loads(data['identity_ticket'],salt=IDENTITY_SALT);self.assertEqual(payload['subject'],hashlib.sha256((settings.WECHAT_APP_ID+'\0provider-verified-subject').encode()).hexdigest())
        self.assertTrue(provider.call_args.args[0].startswith('https://api.weixin.qq.com/sns/jscode2session?'))
    def test_provider_expired_code_is_not_accepted(self):
        reply=MagicMock();reply.__enter__.return_value=io.StringIO(json.dumps({'errcode':40163,'errmsg':'code been used'}))
        with patch('core.account_access.urlopen',return_value=reply):self.assertEqual(self.post('wechat',dict(code='used-code',privacy_accepted=True)).status_code,401)
    def test_provider_transport_failure_is_controlled(self):
        with patch('core.account_access.urlopen',side_effect=OSError('provider offline')):
            r=self.post('wechat',dict(code='some-code',privacy_accepted=True));self.assertEqual(r.status_code,503);self.assertNotIn('provider offline',r.content.decode())
    def test_explicit_privacy_consent_is_required(self):
        for value in [False,'true',1,None]:
            self.assertEqual(self.post('wechat',dict(code='some-code',privacy_accepted=value)).status_code,422)
            self.assertEqual(self.post('register',self.registration(privacy_accepted=value)).status_code,422)
    def test_patient_registration_grants_only_own_scope(self):
        b=self.registration(role_code='director',scope_kind='group');result=self.ok(self.post('register',b));self.assertEqual(result['state'],'registered')
        login=self.ok(self.post('login',{'login_name':b['login_name'],'password':b['password']}));self.assertEqual(len(login['scopes']),1);self.assertEqual(login['scope']['role_code'],'patient');self.assertEqual(login['scope']['scope_kind'],'self')
        c=Client(HTTP_AUTHORIZATION='Bearer '+login['token']);workspace=self.ok(c.get('/api/workspace'));self.assertEqual([p['id'] for p in workspace['resources']['patients']],[login['account']['patient_id']]);self.assertNotIn('UC16',[x['code'] for x in workspace['menu']])
        p=get('patient',login['account']['patient_id']);self.assertEqual(p['allergy_declaration'],'unknown')
    def test_staff_cannot_self_register_elevated_identity(self):
        before=one('SELECT count(*) AS n FROM user_account')['n'];self.assertEqual(self.post('register',self.registration(account_kind='employee')).status_code,422);self.assertEqual(one('SELECT count(*) AS n FROM user_account')['n'],before)
    def test_duplicate_patient_is_not_claimed_or_duplicated(self):
        p=one('SELECT * FROM patient ORDER BY id LIMIT 1');before=one('SELECT count(*) AS n FROM patient')['n']
        b=self.registration(full_name=p['full_name'],birth_date=p['birth_date'].isoformat(),phone=p['phone']);self.assertEqual(self.post('register',b).status_code,409);self.assertEqual(one('SELECT count(*) AS n FROM patient')['n'],before);self.assertIsNone(one('SELECT id FROM user_account WHERE login_name=%s',[b['login_name']]))
    def test_representative_registration_has_no_patient_access(self):
        b=self.registration(account_kind='representative');r=self.ok(self.post('register',b));self.assertEqual(r['state'],'authorization_pending');a=one('SELECT * FROM user_account WHERE login_name=%s',[b['login_name']]);self.assertIsNone(one('SELECT id FROM account_scope WHERE account_id=%s',[a['id']]));self.assertEqual(self.post('login',dict(login_name=b['login_name'],password=b['password'])).status_code,403)
    def test_minor_and_invalid_birth_are_not_registered(self):
        for birth in ['not-a-date','2999-01-01','2020-01-01']:
            b=self.registration(birth_date=birth);self.assertEqual(self.post('register',b).status_code,422);self.assertIsNone(one('SELECT id FROM user_account WHERE login_name=%s',[b['login_name']]))
    def test_registration_failure_rolls_back_patient(self):
        b=self.registration();before=one('SELECT count(*) AS n FROM patient')['n']
        def after_patient(table,values):
            if table=='user_account':raise ValueError('fail after patient was inserted')
            return original_insert(table,values)
        with patch('core.account_access.insert',side_effect=after_patient):self.assertEqual(self.post('register',b).status_code,400)
        self.assertEqual(one('SELECT count(*) AS n FROM patient')['n'],before)
    def test_wechat_registration_replay_reuses_account(self):
        b=self.registration(identity_ticket=self.proof(),login_name='',password='');first=self.ok(self.post('register',b));before=one('SELECT count(*) AS n FROM patient')['n'];second=self.ok(self.post('register',dict(b,full_name='不同姓名不得重复新建')))
        self.assertEqual([a['id'] for a in first['identities']],[a['id'] for a in second['identities']]);self.assertEqual(one('SELECT count(*) AS n FROM patient')['n'],before)
    def test_staff_binding_requires_actual_password(self):
        r=self.post('wechat/bind',dict(identity_ticket=self.proof(),login_name='dentist',password='incorrect',role_code='director'));self.assertEqual(r.status_code,401);self.assertEqual(len(choice(self.subject)['identities']),0)
        result=self.post('wechat/bind',dict(identity_ticket=self.proof(),login_name='dentist',password=os.environ['DEMO_PASSWORD']));self.assertEqual(result.status_code,403);self.assertEqual(choice(self.subject)['identities'],[])
    def test_another_wechat_cannot_silently_take_binding(self):
        a=self.mapped();old=self.subject;self.subject=hashlib.sha256(b'another-test-wechat').hexdigest();r=self.post('wechat/bind',dict(identity_ticket=self.proof(),login_name='patient',password=os.environ['DEMO_PASSWORD']));self.assertEqual(r.status_code,409);self.assertEqual(one('SELECT subject_hash FROM adc_auth.wechat_identity WHERE account_id=%s AND revoked_at IS NULL',[a['id']])['subject_hash'],old)
    def test_one_wechat_can_choose_only_verified_business_accounts(self):
        patient=self.mapped();doctor=self.mapped('dentist');data=choice(self.subject);self.assertEqual({a['id'] for a in data['identities']},{patient['id']})
        scope=one('SELECT id FROM account_scope WHERE account_id=%s AND revoked_at IS NULL',[doctor['id']]);login=self.post('wechat/select',dict(identity_ticket=data['identity_ticket'],account_id=doctor['id'],scope_id=scope['id']));self.assertEqual(login.status_code,403)
    def test_cross_account_and_scope_injection_are_denied(self):
        a=self.mapped();director=self.account('director');scope=one('SELECT id FROM account_scope WHERE account_id=%s',[director['id']]);proof=self.proof()
        for target in [a['id'],director['id']]:self.assertEqual(self.post('wechat/select',dict(identity_ticket=proof,account_id=target,scope_id=scope['id'])).status_code,403)
    def test_expired_or_tampered_identity_proof_is_denied(self):
        a=self.mapped();scope=one('SELECT id FROM account_scope WHERE account_id=%s',[a['id']])
        with patch('django.core.signing.time.time',return_value=time.time()-301):old=self.proof()
        for proof in [old,'forged-ticket']:
            self.assertEqual(self.post('wechat/select',dict(identity_ticket=proof,account_id=a['id'],scope_id=scope['id'])).status_code,401)
    def test_binding_revocation_and_account_disable_take_effect(self):
        a=self.mapped();scope=one('SELECT id FROM account_scope WHERE account_id=%s',[a['id']]);body=dict(identity_ticket=self.proof(),account_id=a['id'],scope_id=scope['id'])
        execute('UPDATE adc_auth.wechat_identity SET revoked_at=now() WHERE account_id=%s',[a['id']]);self.assertEqual(self.post('wechat/select',body).status_code,403)
        execute('UPDATE adc_auth.wechat_identity SET revoked_at=NULL WHERE account_id=%s',[a['id']]);execute('UPDATE user_account SET is_enabled=false WHERE id=%s',[a['id']]);self.assertEqual(self.post('wechat/select',body).status_code,401)
    def test_scope_and_representative_authority_revocation_take_effect(self):
        a=self.mapped('representative');scope=one('SELECT id FROM account_scope WHERE account_id=%s',[a['id']]);body=dict(identity_ticket=self.proof(),account_id=a['id'],scope_id=scope['id'])
        execute('UPDATE patient_authority SET revoked_at=now() WHERE authorized_account_id=%s',[a['id']]);self.assertEqual(self.post('wechat/select',body).status_code,403);self.assertEqual(choice(self.subject)['identities'][0]['scopes'],[])
    def test_recovery_requires_own_wechat_binding(self):
        self.mapped();other=self.account('director');self.assertEqual(self.post('recovery',dict(identity_ticket=self.proof(),account_id=other['id'])).status_code,403)
    def test_password_reset_is_one_time_and_invalidates_old_session(self):
        a=self.mapped();old=self.ok(self.post('login',dict(login_name='patient',password=os.environ['DEMO_PASSWORD'])))['token'];ticket=self.ok(self.post('recovery',dict(identity_ticket=self.proof(),account_id=a['id'])))['reset_ticket'];password='NewCredential!2026'
        self.ok(self.post('reset-password',dict(reset_ticket=ticket,password=password)))
        self.assertEqual(Client(HTTP_AUTHORIZATION='Bearer '+old).get('/api/workspace').status_code,401)
        self.assertEqual(self.post('login',dict(login_name='patient',password=os.environ['DEMO_PASSWORD'])).status_code,401)
        self.assertEqual(self.post('login',dict(login_name='patient',password=password)).status_code,200)
        self.assertEqual(self.post('reset-password',dict(reset_ticket=ticket,password='AnotherCredential!2026')).status_code,401)
        events=rows("SELECT changed_fields FROM audit_event WHERE account_id=%s AND operation_name='auth.password_reset'",[a['id']]);self.assertEqual(len(events),1);self.assertNotIn(password,str(events))
    def test_reset_rejects_weak_password_without_consuming_proof(self):
        a=self.mapped();ticket=self.ok(self.post('recovery',dict(identity_ticket=self.proof(),account_id=a['id'])))['reset_ticket'];self.assertEqual(self.post('reset-password',dict(reset_ticket=ticket,password='short')).status_code,422);self.assertEqual(self.post('reset-password',dict(reset_ticket=ticket,password='StrongEnough!2026')).status_code,200)
    def wechat_session(self,role='patient'):
        a=self.mapped(role);scope=one('SELECT id FROM account_scope WHERE account_id=%s AND revoked_at IS NULL',[a['id']]);login=self.ok(self.post('wechat/select',dict(identity_ticket=self.proof(),account_id=a['id'],scope_id=scope['id'])))
        return a,scope,Client(HTTP_AUTHORIZATION='Bearer '+login['token'])
    def unbind(self,actor,account):
        return self.clients[actor].post('/api/use-cases/UC16',data=json.dumps({'action':'unbind-wechat','id':account['id'],'reason':'合成身份核实工单 AUTH-TEST'}),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
    def test_admin_unbind_revokes_wechat_but_preserves_password_session(self):
        a,scope,client=self.wechat_session();self.assertEqual(client.get('/api/workspace').status_code,200);self.ok(self.unbind('reception',a));self.assertEqual(client.get('/api/workspace').status_code,401);self.assertEqual(self.clients['patient'].get('/api/workspace').status_code,200)
        row=one('SELECT * FROM adc_auth.wechat_identity WHERE account_id=%s',[a['id']]);self.assertIsNotNone(row['revoked_at']);self.assertEqual(row['revocation_basis'],'合成身份核实工单 AUTH-TEST')
    def test_scope_switch_does_not_bypass_wechat_revocation(self):
        a,scope,client=self.wechat_session();r=self.ok(client.post('/api/auth/scope',data=json.dumps({'scope_id':scope['id']}),content_type='application/json'));self.ok(self.unbind('reception',a));self.assertEqual(Client(HTTP_AUTHORIZATION='Bearer '+r['token']).get('/api/workspace').status_code,401)
    def test_wechat_session_cannot_be_accepted_by_old_password_only_release(self):
        a,scope,client=self.wechat_session();value=client.defaults['HTTP_AUTHORIZATION'][7:]
        with self.assertRaises(signing.BadSignature):signing.loads(value,salt='adc-access',max_age=8*3600)
        self.assertEqual(signing.loads(value,salt='adc-wechat-access-v1')['account'],a['id'])
        password=self.ok(self.post('login',dict(login_name='patient',password=os.environ['DEMO_PASSWORD'])))['token']
        self.assertEqual(signing.loads(password,salt='adc-access')['account'],a['id'])
    def test_unbind_requires_textual_identity_verification_basis(self):
        a=self.mapped()
        for reason in [None,123,[],{},'  ']:
            r=self.clients['reception'].post('/api/use-cases/UC16',data=json.dumps(dict(action='unbind-wechat',id=a['id'],reason=reason)),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(r.status_code,422,r.content)
        self.assertIsNone(one('SELECT revoked_at FROM adc_auth.wechat_identity WHERE account_id=%s',[a['id']])['revoked_at'])
    def test_business_cannot_unbind_elevated_headquarters_account(self):
        a=self.mapped('director');self.assertEqual(self.unbind('business',a).status_code,403);self.assertIsNone(one('SELECT revoked_at FROM adc_auth.wechat_identity WHERE account_id=%s',[a['id']])['revoked_at'])
    def test_verified_rebinding_invalidates_original_recovery_ticket(self):
        a=self.mapped();ticket=self.ok(self.post('recovery',dict(identity_ticket=self.proof(),account_id=a['id'])))['reset_ticket'];self.ok(self.unbind('reception',a));self.subject=hashlib.sha256(b'rebound-provider-identity').hexdigest();self.ok(self.post('wechat/bind',dict(identity_ticket=self.proof(),login_name='patient',password=os.environ['DEMO_PASSWORD'])))
        self.assertEqual(self.post('reset-password',dict(reset_ticket=ticket,password='CannotReuseProof!2026')).status_code,403);self.assertEqual(one('SELECT count(*) AS n FROM adc_auth.wechat_identity WHERE account_id=%s AND revoked_at IS NULL',[a['id']])['n'],1)

class AccountAccessConcurrencyTests(unittest.TestCase):
    def test_duplicate_registration_waits_for_uncommitted_patient(self):
        """A concurrent caller must not create a second record hidden by the first transaction."""
        suffix=uuid.uuid4().hex[:16]
        names=['auth_duplicate_a_'+suffix,'auth_duplicate_b_'+suffix]
        body=dict(account_kind='patient',full_name='并发建档核查 '+suffix,birth_date='2000-01-01',phone='136'+str(uuid.uuid4().int)[:8],billing_address='合成地址',emergency_name='合成紧急联系人',emergency_phone='13900009999',emergency_relationship='亲属',password='InitialPassword!2026',privacy_accepted=True)
        first_created=Event();release_first=Event();second_started=Event();application='adc-registration-check-'+suffix
        def worker(index):
            try:
                execute('SET application_name = %s',[application+'-'+str(index)])
                if index==1:
                    with transaction.atomic():
                        result=Client().post('/api/auth/register',data=json.dumps(dict(body,login_name=names[0])),content_type='application/json')
                        self.assertEqual(result.status_code,200,result.content)
                        first_created.set()
                        self.assertTrue(release_first.wait(15),'Release the first test transaction')
                        return result.status_code
                second_started.set()
                return Client().post('/api/auth/register',data=json.dumps(dict(body,login_name=names[1])),content_type='application/json').status_code
            finally:connection.close()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(worker,1)
                try:
                    self.assertTrue(first_created.wait(10),'First registration must reach the uncommitted state')
                    second=pool.submit(worker,2);self.assertTrue(second_started.wait(5))
                    deadline=time.monotonic()+8;waiting=False
                    while time.monotonic()<deadline and not second.done():
                        waiting=bool(one("SELECT pid FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock'",[application+'-2']))
                        if waiting:break
                        time.sleep(.025)
                    self.assertTrue(waiting,'Second registration created a duplicate instead of waiting for the first transaction')
                finally:release_first.set()
                self.assertEqual(first.result(timeout=10),200)
                self.assertEqual(second.result(timeout=10),409)
            self.assertEqual(one('SELECT count(*) AS n FROM patient WHERE full_name=%s AND birth_date=%s AND phone=%s',[body['full_name'],body['birth_date'],body['phone']])['n'],1)
            self.assertEqual(one('SELECT count(*) AS n FROM user_account WHERE login_name=ANY(%s)',[names])['n'],1)
        finally:
            release_first.set()
            accounts=rows('SELECT id,patient_id FROM user_account WHERE login_name=ANY(%s)',[names])
            with transaction.atomic():
                for account in accounts:
                    execute('DELETE FROM audit_event WHERE account_id=%s',[account['id']]);execute('DELETE FROM account_scope WHERE account_id=%s',[account['id']]);execute('DELETE FROM patient_revision WHERE recorded_account_id=%s',[account['id']]);execute('DELETE FROM patient_contact WHERE recorded_account_id=%s',[account['id']]);execute('DELETE FROM user_account WHERE id=%s',[account['id']]);execute('DELETE FROM patient WHERE id=%s',[account['patient_id']])
    def test_only_one_concurrent_reset_consumes_same_credential(self):
        execute((settings.CONTRACTS_DIR/'auth-001.sql').read_text())
        name='auth_race_'+uuid.uuid4().hex[:20];account=None
        def post(path,body):return Client().post('/api/auth/'+path,data=json.dumps(body),content_type='application/json')
        try:
            response=post('register',dict(account_kind='patient',full_name='并发凭据测试',birth_date='2000-01-01',phone='137'+str(uuid.uuid4().int)[:8],billing_address='合成地址',emergency_name='合成紧急联系人',emergency_phone='13900009999',emergency_relationship='亲属',login_name=name,password='InitialPassword!2026',privacy_accepted=True));self.assertEqual(response.status_code,200,response.content)
            account=one('SELECT * FROM user_account WHERE login_name=%s',[name]);subject=hashlib.sha256(name.encode()).hexdigest()
            with transaction.atomic():bind_identity(subject,account)
            recovery=post('recovery',dict(identity_ticket=choice(subject)['identity_ticket'],account_id=account['id']));self.assertEqual(recovery.status_code,200,recovery.content);ticket=recovery.json()['reset_ticket'];barrier=Barrier(2)
            def worker(index):
                try:
                    barrier.wait(timeout=10)
                    return post('reset-password',dict(reset_ticket=ticket,password='ConcurrentPassword!2026-'+str(index))).status_code
                finally:connection.close()
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(worker,[1,2]))
            self.assertEqual(sorted(statuses),[200,401]);self.assertEqual(one("SELECT count(*) AS n FROM audit_event WHERE account_id=%s AND operation_name='auth.password_reset'",[account['id']])['n'],1)
        finally:
            if account:
                self.assertEqual(one('SELECT login_name FROM user_account WHERE id=%s',[account['id']])['login_name'],name)
                with transaction.atomic():
                    execute('DELETE FROM adc_auth.wechat_identity WHERE account_id=%s',[account['id']]);execute('DELETE FROM audit_event WHERE account_id=%s',[account['id']]);execute('DELETE FROM account_scope WHERE account_id=%s',[account['id']]);execute('DELETE FROM patient_revision WHERE recorded_account_id=%s',[account['id']]);execute('DELETE FROM patient_contact WHERE recorded_account_id=%s',[account['id']]);execute('DELETE FROM user_account WHERE id=%s',[account['id']]);execute('DELETE FROM patient WHERE id=%s',[account['patient_id']])

if __name__=='__main__':unittest.main(verbosity=2)
