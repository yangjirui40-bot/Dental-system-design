import os,sys,json,uuid,unittest
from pathlib import Path
test_database=os.environ.get('POSTGRES_DB','')
if not (test_database.startswith(('adc_test_','adc_ui_check_')) or test_database=='adc_acceptance'):
    raise SystemExit('拒绝在业务数据库运行写入测试。请显式设置独立的 adc_test_*、adc_ui_check_* 或 adc_acceptance 数据库。')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','adc.settings')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import django
django.setup()
from django.test import Client
from django.db import connection
from django.utils import timezone
from datetime import timedelta,datetime,time
from zoneinfo import ZoneInfo
from core.db import rows,one,get,insert,execute,update
from core.rules import acyclic,split_cost,aggregate_fund
from core.security import BusinessError

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clients={}
        for role in ['patient','representative','reception','dentist','business','manager','finance','director']:
            c=Client();r=c.post('/api/auth/login',data=json.dumps({'login_name':role,'password':os.environ['DEMO_PASSWORD']}),content_type='application/json');assert r.status_code==200,r.content
            c.defaults['HTTP_AUTHORIZATION']='Bearer '+r.json()['token'];cls.clients[role]=c
    def setUp(self):
        from django.db import transaction
        self.tx=transaction.atomic();self.tx.__enter__()
        self.addCleanup(self.rollback)
    def rollback(self):
        from django.db import transaction
        transaction.set_rollback(True);self.tx.__exit__(None,None,None)
    def post(self,role,code,body,key=None):
        return self.clients[role].post('/api/use-cases/'+code,data=json.dumps(body,default=str),content_type='application/json',HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))
    def booking(self,offset=1):
        day=timezone.localdate()+timedelta(days=offset);d=one("SELECT * FROM practice_duty WHERE publication_state='published' AND (starts_at AT TIME ZONE 'Asia/Shanghai')::date=%s ORDER BY id LIMIT 1",[day]);op=one("SELECT id FROM operatory WHERE clinic_id=%s AND resource_state='active' ORDER BY id LIMIT 1",[d['clinic_id']]);patient=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'");s=one("SELECT id FROM treatment_standard WHERE approval_state='approved' ORDER BY id LIMIT 1")
        return dict(action='book',patient_id=patient['id'],clinic_id=d['clinic_id'],dentist_id=d['dentist_id'],duty_id=d['id'],operatory_id=op['id'],starts_at=d['starts_at'],ends_at=d['starts_at']+timedelta(minutes=30),standard_ids=[s['id']],presenting_request='初步检查')
    def test_01_all_eight_workspaces(self):
        for role,c in self.clients.items():
            r=c.get('/api/workspace');self.assertEqual(r.status_code,200,(role,r.content));self.assertNotIn('password_hash',r.content.decode())
    def test_02_exact_schema(self):
        self.assertEqual(one("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")['n'],58)
        self.assertEqual(one("SELECT count(*) AS n FROM information_schema.table_constraints WHERE constraint_type='FOREIGN KEY' AND table_schema='public'")['n'],163)
    def test_03_patient_cannot_read_others_invoice(self):
        p=one('SELECT * FROM patient LIMIT 1');p2=insert('patient',dict(account_no='OTHER-PATIENT',full_name='其他演示患者',birth_date='2000-01-01',billing_address='虚构',phone='13800000000',allergy_declaration='unknown',row_version=1,created_at=timezone.now()))
        b=self.booking();b['patient_id']=p2['id'];r=self.post('patient','UC02',b);self.assertEqual(r.status_code,403,r.content)
    def test_04_book_and_same_key_replay(self):
        baseline=one('SELECT count(*) AS n FROM appointment')['n'];key=str(uuid.uuid4());b=self.booking();r=self.post('patient','UC02',b,key);self.assertEqual(r.status_code,200,r.content);r2=self.post('patient','UC02',b,key);self.assertEqual(r2.status_code,200,r2.content);self.assertTrue(r2.json()['replayed']);self.assertEqual(one('SELECT count(*) AS n FROM appointment')['n'],baseline+1)
    def test_05_reusing_key_with_other_payload_rejected(self):
        key=str(uuid.uuid4());b=self.booking();self.assertEqual(self.post('patient','UC02',b,key).status_code,200);b['special_needs']='另一个请求';self.assertEqual(self.post('patient','UC02',b,key).status_code,409)
    def test_06_double_booking_rejected(self):
        b=self.booking();self.assertEqual(self.post('patient','UC02',b).status_code,200);self.assertEqual(self.post('patient','UC02',b).status_code,409)
    def test_07_invalid_operatory_rejected(self):
        b=self.booking();other=one('SELECT id FROM operatory WHERE clinic_id<>%s LIMIT 1',[b['clinic_id']]);b['operatory_id']=other['id'];self.assertEqual(self.post('patient','UC02',b).status_code,422)
    def test_08_stopped_duty_rejected(self):
        b=self.booking();execute("UPDATE practice_duty SET publication_state='stopped' WHERE id=%s",[b['duty_id']]);self.assertEqual(self.post('patient','UC02',b).status_code,422)
    def test_09_missing_qualification_rejected(self):
        b=self.booking();execute("UPDATE dentist_qualification SET verification_result='rejected' WHERE dentist_id=%s",[b['dentist_id']]);self.assertEqual(self.post('patient','UC02',b).status_code,422)
    def test_10_patient_cannot_confirm_clinical(self):
        self.assertEqual(self.post('patient','UC05',{'action':'sign','encounter_id':1}).status_code,403)
    def test_11_patient_cannot_self_grant(self):
        self.assertEqual(self.post('patient','UC16',{'action':'grant'}).status_code,403)
    def test_12_reception_cannot_grant_employee_role(self):
        a=one("SELECT id FROM user_account WHERE login_name='dentist'");role=one("SELECT id FROM access_role WHERE role_code='dentist'")
        self.assertEqual(self.post('reception','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='group')).status_code,403)
    def test_13_cancellation_keeps_history(self):
        a=self.post('patient','UC02',self.booking()).json();r=self.post('patient','UC03',dict(action='cancel',id=a['id'],row_version=1,reason='个人原因'));self.assertEqual(r.status_code,200,r.content);self.assertEqual(get('appointment',a['id'])['resolution'],'cancelled');self.assertEqual(one('SELECT count(*) AS n FROM appointment_event WHERE appointment_id=%s',[a['id']])['n'],1)
    def test_14_failed_reschedule_preserves_old(self):
        b=self.booking();a=self.post('patient','UC02',b).json();replacement=dict(b);replacement['operatory_id']=999999;r=self.post('patient','UC03',dict(action='reschedule',id=a['id'],row_version=1,reason='改期',replacement=replacement));self.assertEqual(r.status_code,422);self.assertEqual(get('appointment',a['id'])['resolution'],'booked')
    def test_15_representative_authority_required(self):
        execute('UPDATE patient_authority SET revoked_at=now()');self.assertEqual(self.post('representative','UC02',self.booking()).status_code,403)
    def test_16_cycle_rejected(self):
        with self.assertRaises(BusinessError):acyclic([1,2,3],[(1,2),(2,3),(3,1)])
    def test_17_cost_sum_and_negative_fund(self):
        with self.assertRaises(BusinessError):split_cost(100,[{'allocated_amount':90}])
        self.assertEqual(aggregate_fund([100,-150]),(-50,0))
    def test_18_unreviewed_quarter_cannot_confirm(self):
        q=one('SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[timezone.localdate(),timezone.localdate()]);r=self.post('director','UC12',dict(action='confirm',quarter_id=q['id']));self.assertEqual(r.status_code,422,r.content)
    def test_19_clinical_detail_denied_for_finance(self):
        self.assertEqual(self.clients['finance'].get('/api/encounters/1').status_code,403)
    def test_20_audit_not_patient_visible(self):
        self.assertEqual(self.clients['patient'].get('/api/audit').status_code,403)
    def test_21_no_passwords_in_audit(self):
        r=self.clients['director'].get('/api/audit');self.assertEqual(r.status_code,200,r.content);self.assertNotIn('password_hash',r.content.decode())
    def test_22_complete_clinical_invoice(self):
        # Fixed synthetic same-day encounter avoids depending on current time.
        b=self.booking();day=timezone.localdate();start=datetime.combine(day,time(9),ZoneInfo('Asia/Shanghai'));now=timezone.now();d=one("SELECT * FROM practice_duty WHERE (starts_at AT TIME ZONE 'Asia/Shanghai')::date=%s LIMIT 1",[day]);b.update(duty_id=d['id'],starts_at=start,ends_at=start+timedelta(minutes=30));b.pop('action');b.pop('standard_ids')
        a=insert('appointment',dict(**b,appointment_no='A-TEST-TODAY',resolution='booked',created_at=now,row_version=1,request_channel='patient_portal',created_account_id=one("SELECT id FROM user_account WHERE login_name='patient'")['id']))
        r=self.post('patient','UC04',dict(action='arrive',appointment_id=a['id']));self.assertEqual(r.status_code,200,r.content);self.assertFalse(get('appointment',a['id'])['has_attended'])
        r=self.post('dentist','UC04',dict(action='start',appointment_id=a['id'],identity_confirmed=True,allergy_confirmed=True));self.assertEqual(r.status_code,200,r.content);en=r.json();self.assertTrue(get('appointment',a['id'])['has_attended'])
        s=one("SELECT * FROM treatment_standard WHERE approval_state='approved' ORDER BY id LIMIT 1")
        from core.clinical import NOTE_FIELDS
        body=dict(action='sign',encounter_id=en['id'],**{k:'教学演示已核实内容' for k in NOTE_FIELDS},consent_scope='已说明并同意本次初步检查',evidence_reference='患者当次同意核实记录',treatments=[dict(standard_id=s['id'],actual_quantity=1,charged_unit_price=str(s['unit_price']),implementation_result='performed')])
        r=self.post('dentist','UC05',body);self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['billing_state'],'current',r.content);invoice=one('SELECT * FROM invoice WHERE encounter_id=%s',[en['id']]);self.assertIsNotNone(invoice);rev=one("SELECT * FROM invoice_revision WHERE invoice_id=%s AND validity='current'",[invoice['id']]);self.assertEqual(rev['issued_by'],a['dentist_id']);self.assertEqual(rev['total_amount'],s['unit_price'])
        r=self.clients['patient'].get('/api/invoices/'+str(invoice['id']));self.assertEqual(r.status_code,200,r.content);self.assertEqual(len(r.json()['lines']),1)
    def test_23_missing_idempotency_rejected(self):
        r=self.clients['patient'].post('/api/use-cases/UC02',data=json.dumps(self.booking(),default=str),content_type='application/json');self.assertEqual(r.status_code,400)
    def test_24_failed_login_no_identity_disclosure(self):
        r=Client().post('/api/auth/login',data=json.dumps({'login_name':'unknown','password':'incorrect'}),content_type='application/json');self.assertEqual(r.status_code,401)
    def test_25_clinic_and_employee_creation(self):
        r=self.post('business','UC07',dict(action='save',clinic_name='测试门店',postal_address='虚构地址',phone='02000000000',email='new@example.invalid',floor_area=100,opened_on='2020-01-01'));self.assertEqual(r.status_code,200,r.content)
        r=self.post('business','UC08',dict(action='employee',full_name='新职员',birth_date='1990-01-01',home_address='虚构地址',phone='13800000000',email='newemployee@example.invalid',employed_from='2020-01-01'));self.assertEqual(r.status_code,200,r.content)
        e=r.json();r=self.post('business','UC08',dict(action='dentist',employee_id=e['id'],professional_no='TEST-PRO'));self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['id'],e['id'])
    def test_26_standard_maker_checker(self):
        c=self.post('business','UC10',dict(action='catalog',treatment_code='TEST-S',treatment_name='测试项目')).json()
        b=dict(action='draft',treatment_id=c['id'],treatment_name='测试项目',unit_name='次',quantity_scale=0,unit_price=12.34,site_requirement='核实部位',duration_minutes=30,valid_from=(timezone.now()+timedelta(days=1)).isoformat())
        r=self.post('business','UC10',b);self.assertEqual(r.status_code,200,r.content);s=r.json();r=self.post('business','UC10',dict(action='approve',id=s['id']));self.assertEqual(r.status_code,403);r=self.post('director','UC10',dict(action='approve',id=s['id']));self.assertEqual(r.status_code,200,r.content)
    def test_27_cost_review_and_quarter_source_snapshot(self):
        self.test_22_complete_clinical_invoice();a=one('SELECT * FROM appointment ORDER BY id DESC LIMIT 1');q=one('SELECT id FROM fiscal_quarter WHERE starts_on<=%s AND ends_before>%s',[timezone.localdate(),timezone.localdate()])
        r=self.post('finance','UC11',dict(action='source',source_document_no='TEST-COST-1',source_line_no=1,cost_category='supplies',document_date=str(timezone.localdate()),evidence_reference='测试凭据',source_amount='80.50',allocations=[dict(quarter_id=q['id'],dentist_id=a['dentist_id'],clinic_id=a['clinic_id'],allocated_amount='80.50',allocation_basis='实际用品归属')]));self.assertEqual(r.status_code,200,r.content)
        rev=r.json();alloc=one('SELECT * FROM cost_allocation WHERE cost_revision_id=%s',[rev['id']]);r=self.post('manager','UC11',dict(action='review',id=alloc['id'],approved=True));self.assertEqual(r.status_code,200,r.content)
        s=self.post('finance','UC11',dict(action='submission',quarter_id=q['id'],dentist_id=a['dentist_id'],clinic_id=a['clinic_id'],supplies_complete=True,operating_complete=True));self.assertEqual(s.status_code,200,s.content);r=self.post('manager','UC11',dict(action='review-submission',id=s.json()['id'],approved=True));self.assertEqual(r.status_code,200,r.content)
        r=self.clients['director'].get('/api/reports?quarter_id='+str(q['id']));self.assertEqual(r.status_code,200,r.content);self.assertFalse(r.json()['issues'],r.content);self.assertEqual(r.json()['incentive_fund'],'0.00')
        r=self.post('director','UC12',dict(action='confirm',quarter_id=q['id']));self.assertEqual(r.status_code,200,r.content);self.assertEqual(one('SELECT count(*) AS n FROM report_invoice_source WHERE report_id=%s',[r.json()['id']])['n'],1)
    def test_28_plan_phase_and_cancellation_continuity(self):
        self.test_22_complete_clinical_invoice();en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');a=get('appointment',en['appointment_id']);s=one('SELECT id FROM treatment_standard ORDER BY id LIMIT 1')
        phases=[dict(phase_no=1,phase_title='后续治疗',clinical_condition='牙医已核实可约',responsible_clinic_id=a['clinic_id'],clinical_released=True,items=[dict(standard_id=s['id'],planned_quantity=1)]),dict(phase_no=2,phase_title='后续复查',clinical_condition='等待前阶段结果',responsible_clinic_id=a['clinic_id'],clinical_released=False,items=[])]
        r=self.post('dentist','UC13',dict(action='confirm',encounter_id=en['id'],consent_scope='分阶段治疗',evidence_reference='本人同意依据',phases=phases,dependencies=[[1,2]]));self.assertEqual(r.status_code,200,r.content);plan=r.json();p=one('SELECT * FROM treatment_phase WHERE plan_id=%s AND phase_no=1',[plan['id']]);b=self.booking();b['phase_id']=p['id'];r=self.post('patient','UC02',b);self.assertEqual(r.status_code,200,r.content);new=r.json();r=self.post('patient','UC03',dict(action='cancel',id=new['id'],row_version=1,reason='调整个人时间'));self.assertEqual(r.status_code,200,r.content);self.assertIsNotNone(one('SELECT * FROM followup_task WHERE phase_id=%s AND closed_at IS NULL',[p['id']]));self.assertEqual(get('treatment_phase',p['id'])['progress_outcome'],'ready')
    def test_29_price_override_requires_real_manager(self):
        self.test_22_complete_clinical_invoice();en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');old=one("SELECT * FROM clinical_note WHERE encounter_id=%s AND signature_state='signed'",[en['id']]);s=one('SELECT * FROM treatment_standard ORDER BY id LIMIT 1');from core.clinical import NOTE_FIELDS
        b=dict(action='draft',encounter_id=en['id'],previous_note_id=old['id'],correction_reason='纠正实际费用依据',**{k:'已核实' for k in NOTE_FIELDS},treatments=[dict(standard_id=s['id'],actual_quantity=1,charged_unit_price='10.00',implementation_result='performed')])
        r=self.post('dentist','UC05',b);self.assertEqual(r.status_code,200,r.content);self.assertEqual(get('clinical_note',old['id'])['signature_state'],'signed')
        r=self.post('manager','UC06',dict(action='approve-price',encounter_id=en['id'],standard_id=s['id'],price='10.00',basis='主管核实非标准计价'));self.assertEqual(r.status_code,200,r.content)
        b.update(action='sign',consent_scope='本次实际检查',evidence_reference='同意核实记录');r=self.post('dentist','UC05',b);self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['billing_state'],'pending_correction')
        r=self.post('manager','UC06',dict(action='correct',encounter_id=en['id'],correction_reason='批准采用已核实的新计价依据'));self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['current_revision']['total_amount'],'10.00');self.assertEqual(one('SELECT count(*) AS n FROM invoice')['n'],1)
    def test_30_calendar_and_resources(self):
        c=one('SELECT id FROM clinic ORDER BY id LIMIT 1');day=timezone.localdate()+timedelta(days=20);start=datetime.combine(day,time(9),ZoneInfo('Asia/Shanghai'))
        r=self.post('manager','UC15',dict(action='calendar',clinic_id=c['id'],work_date=str(day),session_no=1,is_open=True,starts_at=str(start),ends_at=str(start+timedelta(hours=8))));self.assertEqual(r.status_code,200,r.content)
        r=self.post('manager','UC15',dict(action='operatory',clinic_id=c['id'],operatory_code='TEST-OP',operatory_name='测试诊疗位',resource_state='active'));self.assertEqual(r.status_code,200,r.content)
    def test_31_account_creation_scope_and_disable(self):
        p=one('SELECT id FROM patient LIMIT 1');r=self.post('reception','UC16',dict(action='create',account_kind='patient',patient_id=p['id'],login_name='test-new-patient',display_name='患者独立账号',password='TestOnlyPassword2026'));self.assertEqual(r.status_code,200,r.content);self.assertNotIn('password_hash',r.content.decode());a=r.json();r=self.post('reception','UC16',dict(action='disable',id=a['id']));self.assertEqual(r.status_code,200,r.content);self.assertFalse(get('user_account',a['id'])['is_enabled'])
    def test_32_boolean_string_not_a_confirmation(self):
        r=self.post('dentist','UC04',dict(action='start',appointment_id=1,identity_confirmed='false',allergy_confirmed='false'));self.assertEqual(r.status_code,400)
    def test_33_stop_records_institution_reason(self):
        b=self.booking();a=self.post('patient','UC02',b).json();d=get('practice_duty',b['duty_id']);r=self.post('manager','UC09',dict(action='stop',id=d['id'],row_version=d['row_version'],reason='已核实机构停诊'));self.assertEqual(r.status_code,200,r.content);self.assertEqual(get('appointment',a['id'])['resolution'],'unfulfilled');event=one('SELECT * FROM appointment_event WHERE appointment_id=%s',[a['id']]);self.assertEqual(event['initiator_kind'],'organisation')
    def test_34_cross_clinic_duty_requires_directional_travel(self):
        clinic=one('SELECT id FROM clinic ORDER BY id DESC LIMIT 1');dentist=one('SELECT id FROM dentist LIMIT 1');day=timezone.localdate()+timedelta(days=20);start=datetime.combine(day,time(9),ZoneInfo('Asia/Shanghai'));end=start+timedelta(hours=8)
        r=self.post('business','UC15',dict(action='calendar',clinic_id=clinic['id'],work_date=str(day),session_no=1,is_open=True,starts_at=str(start),ends_at=str(end)));self.assertEqual(r.status_code,200,r.content);cal=r.json()
        body=dict(action='publish',clinic_id=clinic['id'],dentist_id=dentist['id'],calendar_id=cal['id'],starts_at=str(start),ends_at=str(end),qualification_kind_ids=[]);self.assertEqual(self.post('business','UC09',body).status_code,422)
        before=one('SELECT clinic_id FROM practice_duty WHERE dentist_id=%s ORDER BY starts_at DESC LIMIT 1',[dentist['id']]);r=self.post('business','UC09',dict(action='travel-rule',from_clinic_id=before['clinic_id'],to_clinic_id=clinic['id'],minimum_minutes=30,valid_from=str(timezone.localdate()),confirmation_basis='已核实方向及间隔'));self.assertEqual(r.status_code,200,r.content);r=self.post('business','UC09',body);self.assertEqual(r.status_code,200,r.content)
    def test_35_document_rest_booking_url(self):
        r=self.clients['patient'].post('/api/appointments',data=json.dumps(self.booking(),default=str),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(r.status_code,200,r.content)
    def test_36_duty_replacement_preserves_patient_promise(self):
        b=self.booking();a=self.post('patient','UC02',b).json();d=get('practice_duty',b['duty_id']);proposal={k:d[k] for k in ['clinic_id','dentist_id','calendar_id','starts_at','ends_at']}
        body=dict(action='replace',id=d['id'],row_version=d['row_version'],new_duty=proposal)
        r=self.clients['manager'].post('/api/duties/'+str(d['id'])+'/replace',data=json.dumps(body,default=str),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(r.status_code,200,r.content);new=get('appointment',a['id']);self.assertEqual(new['appointment_no'],a['appointment_no']);self.assertEqual(new['starts_at'],datetime.fromisoformat(a['starts_at']));self.assertEqual(new['resolution'],'booked');self.assertNotEqual(new['duty_id'],d['id']);self.assertEqual(get('practice_duty',d['id'])['publication_state'],'superseded')
    def test_37_confirm_saved_plan_same_revision(self):
        self.test_22_complete_clinical_invoice();en=one('SELECT * FROM encounter ORDER BY id DESC LIMIT 1');a=get('appointment',en['appointment_id']);phases=[dict(phase_no=1,phase_title='接续检查',clinical_condition='由接诊牙医复评后可约',responsible_clinic_id=a['clinic_id'],clinical_released=False,items=[])]
        r=self.post('dentist','UC13',dict(action='draft',encounter_id=en['id'],phases=phases));self.assertEqual(r.status_code,200,r.content);plan=r.json();p=one('SELECT id FROM treatment_phase WHERE plan_id=%s',[plan['id']])
        r=self.clients['dentist'].post('/api/plans/'+plan['plan_no']+'/revisions/1/confirm',data=json.dumps(dict(consent_scope='本人分阶段治疗',evidence_reference='本次同意依据',released_phase_ids=[p['id']])),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['revision']['revision_no'],1);self.assertEqual(get('treatment_phase',p['id'])['progress_outcome'],'ready')

    def test_38_director_cannot_self_elevate_and_denial_is_audited(self):
        a=one("SELECT id FROM user_account WHERE login_name='director'");role=one("SELECT id FROM access_role WHERE role_code='business'")
        r=self.post('director','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='group'));self.assertEqual(r.status_code,403,r.content)
        self.assertTrue(one("SELECT id FROM audit_event WHERE account_id=%s AND operation_name='denied.grant'",[a['id']]))
    def test_39_patient_role_cannot_have_group_scope(self):
        a=one("SELECT id,patient_id FROM user_account WHERE login_name='patient'");role=one("SELECT id FROM access_role WHERE role_code='patient'")
        r=self.post('director','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='group'));self.assertEqual(r.status_code,403,r.content)
    def test_40_patient_account_cannot_receive_employee_role(self):
        a=one("SELECT id FROM user_account WHERE login_name='patient'");role=one("SELECT id FROM access_role WHERE role_code='dentist'")
        r=self.post('director','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='group'));self.assertEqual(r.status_code,403,r.content)
    def test_41_representative_grant_requires_current_authority(self):
        a=one("SELECT id FROM user_account WHERE login_name='representative'");role=one("SELECT id FROM access_role WHERE role_code='representative'");v=one('SELECT * FROM patient_authority WHERE authorized_account_id=%s',[a['id']]);update('patient_authority',v['id'],dict(revoked_at=timezone.now()))
        r=self.post('director','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='authorized_patient',patient_id=v['patient_id']));self.assertEqual(r.status_code,403,r.content)
    def test_42_reception_opens_only_verified_representative_scope(self):
        r=self.post('reception','UC16',dict(action='create',account_kind='representative',login_name='test-verified-agent',display_name='测试代办人',password='TestOnlyPassword2026'));self.assertEqual(r.status_code,200,r.content);a=r.json();contact=one('SELECT * FROM patient_contact ORDER BY id LIMIT 1')
        r=self.post('reception','UC01',dict(action='authority',id=contact['patient_id'],contact_id=contact['id'],authorized_account_id=a['id'],permission_scope='booking',evidence_reference='已核实测试授权',valid_from=str(timezone.now()-timedelta(hours=1))));self.assertEqual(r.status_code,200,r.content)
        role=one("SELECT id FROM access_role WHERE role_code='representative'");r=self.post('reception','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='authorized_patient',patient_id=contact['patient_id']));self.assertEqual(r.status_code,200,r.content)
    def test_43_business_preparer_cannot_approve_employee_scope(self):
        a=one("SELECT id FROM user_account WHERE login_name='dentist'");role=one("SELECT id FROM access_role WHERE role_code='manager'")
        r=self.post('business','UC16',dict(action='grant',account_id=a['id'],role_id=role['id'],scope_kind='group'));self.assertEqual(r.status_code,403,r.content)

    def test_44_booking_authority_does_not_expose_profile_or_invoice(self):
        a=one("SELECT id FROM user_account WHERE login_name='representative'");v=one('SELECT id FROM patient_authority WHERE authorized_account_id=%s',[a['id']]);update('patient_authority',v['id'],dict(permission_scope='booking'))
        r=self.clients['representative'].get('/api/workspace');self.assertEqual(r.status_code,200,r.content);d=r.json();self.assertNotIn('UC01',[m['code'] for m in d['menu']]);self.assertEqual(d['resources']['invoices'],[]);self.assertNotIn('billing_address',d['resources']['patients'][0]);self.assertEqual(self.clients['representative'].get('/api/records?resource=patients').status_code,403);self.assertEqual(self.clients['representative'].get('/api/records?resource=invoices').status_code,403)
    def test_45_invoice_authority_does_not_expose_booking_history(self):
        a=one("SELECT id FROM user_account WHERE login_name='representative'");v=one('SELECT id FROM patient_authority WHERE authorized_account_id=%s',[a['id']]);update('patient_authority',v['id'],dict(permission_scope='invoices'))
        r=self.clients['representative'].get('/api/workspace');self.assertEqual(r.status_code,200,r.content);d=r.json();self.assertEqual([m['code'] for m in d['menu']],['UC14']);self.assertEqual(d['resources']['appointments'],[]);self.assertNotIn('phone',d['resources']['patients'][0]);self.assertEqual(self.clients['representative'].get('/api/records?resource=appointments').status_code,403)

    def test_46_patient_record_scope_and_read_only(self):
        p=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'")
        self.assertEqual(self.clients['patient'].get('/api/patients/'+str(p['id'])).status_code,200)
        self.assertEqual(self.clients['patient'].get('/api/patients/'+str(p['id']+99999)).status_code,403)
        self.assertEqual(self.clients['finance'].get('/api/patients/'+str(p['id'])).status_code,403)
        self.assertEqual(self.clients['patient'].post('/api/patients/'+str(p['id']),data='{}',content_type='application/json').status_code,405)
    def test_47_journey_excludes_unconfirmed_plan_and_other_patients(self):
        p=one("SELECT id FROM patient WHERE account_no='P-DEMO-001'")
        r=self.clients['patient'].get('/api/patient-journey',{'patient_id':p['id']});self.assertEqual(r.status_code,200)
        self.assertNotIn('clinical_note',r.content.decode())
        self.assertEqual(self.clients['patient'].get('/api/patient-journey',{'patient_id':p['id']+99999}).status_code,403)
        self.assertEqual(self.clients['finance'].get('/api/patient-journey',{'patient_id':p['id']}).status_code,403)
    def test_48_reschedule_slots_exclude_only_authorised_original(self):
        b=self.booking();created=self.post('patient','UC02',b);self.assertEqual(created.status_code,200)
        q={'clinic_id':b['clinic_id'],'patient_id':b['patient_id'],'date':b['starts_at'].date().isoformat(),'minutes':30,'standard_ids':str(b['standard_ids'][0]),'appointment_id':created.json()['id']}
        r=self.clients['patient'].get('/api/slots',q);self.assertEqual(r.status_code,200,r.content)
        self.assertTrue(any(x['starts_at']==created.json()['starts_at'] and x['dentist_id']==b['dentist_id'] for x in r.json()['slots']))
        q['patient_id']=b['patient_id']+99999
        self.assertEqual(self.clients['patient'].get('/api/slots',q).status_code,403)

class ConcurrencyTests(unittest.TestCase):
    def test_two_workers_only_one_appointment(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections
        source=WorkflowTests();b=source.booking(4);b['starts_at']+=timedelta(minutes=60);b['ends_at']+=timedelta(minutes=60)
        def submit(_):
            close_old_connections();c=Client();r=c.post('/api/auth/login',data=json.dumps({'login_name':'patient','password':os.environ['DEMO_PASSWORD']}),content_type='application/json');c.defaults['HTTP_AUTHORIZATION']='Bearer '+r.json()['token'];r=c.post('/api/use-cases/UC02',data=json.dumps(b,default=str),content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));data=r.json();status=r.status_code;close_old_connections();return status,data
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(x[0] for x in results),[200,409],results)
        a=next(x[1] for x in results if x[0]==200);execute("UPDATE appointment SET resolution='cancelled',row_version=row_version+1 WHERE id=%s",[a['id']])

if __name__=='__main__':unittest.main(verbosity=2)
