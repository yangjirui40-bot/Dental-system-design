from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from .db import rows, one, get, insert, update, execute, business_no, TABLES
from .security import require, ROLE_CODES
from .rules import timestamp, version
from .booking import qualifications, followup, event, change
from .patient_profile import emergency_details,save_emergency,declaration

def patient_action(actor,b):
    action=b.get('action','save');pk=b.get('id') or actor.account['patient_id'];now=timezone.now()
    if action=='save':
        old=get('patient',int(pk),True) if pk else None
        if old:
            if actor.role in ('patient','representative','dentist'):actor.patient_access(old['id'],'profile')
            version(old,b)
        else:actor.allow('reception')
        allowed=['full_name','birth_date','sex_code','billing_address','phone','email']
        data={k:b[k] for k in allowed if k in b};require(all(str(data.get(k,old.get(k) if old else '') or '').strip() for k in ['full_name','birth_date','billing_address','phone']),'请填写姓名、出生日期、账单地址及电话')
        contact=emergency_details(b)
        state=declaration(b.get('allergy_declaration',old['allergy_declaration'] if old else 'unknown'),old['id'] if old else None)
        # A shared family phone or a matching name is a candidate, never an identity.
        candidates=rows('SELECT id FROM patient WHERE id<>%s AND (full_name=%s OR phone=%s) LIMIT 10',[old['id'] if old else 0,data.get('full_name',old['full_name'] if old else ''),data.get('phone',old['phone'] if old else '')]) if not old or any(str(data.get(k,old[k]))!=str(old[k]) for k in ['full_name','phone','birth_date','billing_address']) else []
        if candidates:
            require(b.get('identity_confirmed') is True and str(b.get('identity_check_basis','')).strip(),'存在同名或共用电话候选，请核实出生日期及账单地址，明确为不同患者后记录依据；不能自动合并',409)
        require(b.get('change_reason') or not old,'修改资料须填写原因')
        if old:p=update('patient',old['id'],dict(**data,allergy_declaration=state,row_version=old['row_version']+1))
        else:p=insert('patient',dict(**data,account_no=business_no('P'),allergy_declaration=state,row_version=1,created_at=now))
        save_emergency(p['id'],contact,actor.id,actor.employee,now)
        reason=b.get('change_reason','首次建立')
        if candidates:reason+='；独立身份核实：'+b['identity_check_basis']
        prior=one('SELECT * FROM patient_revision WHERE patient_id=%s ORDER BY revision_no DESC LIMIT 1',[p['id']]);insert('patient_revision',dict(**{k:p[k] for k in allowed},patient_id=p['id'],revision_no=prior['revision_no']+1 if prior else 1,replaces_id=prior['id'] if prior else None,change_reason=reason,recorded_by=actor.employee,recorded_account_id=actor.id,recorded_at=now));return p
    require(pk,'请选择患者');p=get('patient',int(pk));require(p,'患者不存在',404)
    if actor.role in ('patient','representative','dentist'):actor.patient_access(p['id'],'profile')
    if action=='contact':
        return insert('patient_contact',dict(patient_id=p['id'],full_name=b['full_name'],phone=b['phone'],relationship=b['relationship'],contact_purpose=b['contact_purpose'],recorded_by=actor.employee,recorded_account_id=actor.id,recorded_at=now))
    if action=='authority':
        actor.allow('reception','dentist');contact=get('patient_contact',int(b['contact_id']));require(contact and contact['patient_id']==p['id'],'联系人不属于该患者');require(contact['contact_purpose'] in ('guardian','agent') and str(b.get('evidence_reference','')).strip(),'紧急联系人不自动具有代办或临床同意身份，请独立核实相应用途与授权依据')
        account=get('user_account',int(b['authorized_account_id'])) if b.get('authorized_account_id') else None
        require(not b.get('authorized_account_id') or account and account['account_kind']=='representative' and account['is_enabled'],'线上代办须选择有效的独立代办人账号')
        require(b.get('permission_scope') in ('booking','profile','invoices','consent','all'),'请选择已明确核实的授权事项')
        start=timestamp(b['valid_from']);end=timestamp(b['valid_to']) if b.get('valid_to') else None
        require(not end or start<end,'授权失效时点须晚于生效时点')
        return insert('patient_authority',dict(patient_id=p['id'],contact_id=contact['id'],permission_scope=b['permission_scope'],evidence_reference=b['evidence_reference'],valid_from=start,valid_to=end,verified_by=actor.employee,verified_at=now,authorized_account_id=account['id'] if account else None))
    if action=='revoke-authority':
        actor.allow('reception','dentist');v=get('patient_authority',int(b['authority_id']),True);require(v and v['patient_id']==p['id'],'授权记录与患者不符');return update('patient_authority',v['id'],dict(revoked_at=now))
    require(action=='allergy','未知患者资料操作');substance=get('allergy_substance',int(b['substance_id']));require(substance,'过敏物质不存在')
    allergy=one('SELECT * FROM patient_allergy WHERE patient_id=%s AND substance_id=%s FOR UPDATE',[p['id'],substance['id']]) or insert('patient_allergy',dict(patient_id=p['id'],substance_id=substance['id'],first_reported_at=now))
    previous=one('SELECT * FROM allergy_revision WHERE allergy_id=%s ORDER BY revision_no DESC LIMIT 1',[allergy['id']]);verified=b.get('verification_result','reported');require(verified in ('reported','verified','refuted'),'核实结论无效')
    if verified!='reported':actor.allow('dentist')
    if previous:require(b.get('correction_reason'),'过敏修订须保留原因')
    result=insert('allergy_revision',dict(allergy_id=allergy['id'],revision_no=previous['revision_no']+1 if previous else 1,replaces_id=previous['id'] if previous else None,reaction_description=b.get('reaction_description'),reporter_name=actor.account['display_name'],report_source=b.get('report_source','本人或获授权事项申报'),verification_result=verified,verified_by=actor.employee if verified!='reported' else None,verified_at=now if verified!='reported' else None,correction_reason=b.get('correction_reason'),recorded_by=actor.employee,recorded_account_id=actor.id,recorded_at=now));update('patient',p['id'],dict(allergy_declaration='reported',row_version=p['row_version']+1));return result

def clinic_action(actor,b):
    actor.allow('business');action=b.get('action','save')
    if action=='manager':
        require(get('clinic',int(b['clinic_id'])) and get('employee',int(b['employee_id'])),'门店或主管职员不存在')
        return insert('clinic_manager',dict(clinic_id=int(b['clinic_id']),employee_id=int(b['employee_id']),effective_from=timestamp(b['effective_from']),effective_to=timestamp(b['effective_to']) if b.get('effective_to') else None))
    data={k:b[k] for k in ['clinic_name','postal_address','phone','email','floor_area','opened_on','closed_on'] if k in b}
    if b.get('id'):
        old=get('clinic',int(b['id']),True);version(old,b)
        if data.get('closed_on'):require(not one("SELECT id FROM appointment WHERE clinic_id=%s AND resolution IN ('booked','arrived')",[old['id']]),'停用门店前须办结未完成预约')
        return update('clinic',old['id'],dict(**data,row_version=old['row_version']+1))
    return insert('clinic',dict(**data,clinic_no=business_no('C'),row_version=1))

def dentist_action(actor,b):
    actor.allow('business');action=b.get('action','employee')
    if action=='qualification-kind':return insert('qualification_kind',dict(qualification_name=b['qualification_name'],description=b.get('description')))
    if action=='qualification':return insert('dentist_qualification',dict(dentist_id=int(b['dentist_id']),qualification_kind_id=int(b['qualification_kind_id']),certificate_no=b.get('certificate_no'),issuing_organisation=b.get('issuing_organisation'),valid_from=b['valid_from'],valid_to=b.get('valid_to') or None,verification_result=b['verification_result'],verified_by=actor.employee,verified_at=timezone.now()))
    if action=='revoke':
        from .resource_changes import revoke_qualification
        return revoke_qualification(actor,b)
    if action=='dentist':return insert('dentist',dict(id=int(b['employee_id']),professional_no=b.get('professional_no')))
    data={k:b[k] for k in ['full_name','birth_date','home_address','phone','email','employed_from','employed_to'] if k in b}
    if b.get('id'):
        old=get('employee',int(b['id']),True);version(old,b);return update('employee',old['id'],dict(**data,row_version=old['row_version']+1))
    return insert('employee',dict(**data,employee_no=business_no('EMP'),row_version=1))

def validate_duty(actor,b,exclude=None,lock=False):
    clinic=int(b['clinic_id']);actor.clinic_access(clinic);dentist=int(b['dentist_id']);start,end=timestamp(b['starts_at']),timestamp(b['ends_at']);require(start<end and start>timezone.now(),'出诊时段须在未来且起止有效');calendar=get('clinic_calendar',int(b['calendar_id']),lock);require(calendar and calendar['clinic_id']==clinic and calendar['is_open'] and calendar['starts_at']<=start and end<=calendar['ends_at'],'出诊须包含于同店有效营业时段')
    skills=list(map(int,b.get('qualification_kind_ids',[])));require(qualifications(dentist,start,end,skills),'所需专业资格未核实或未覆盖出诊时点')
    if lock:one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',[f'duty:{dentist}'])
    neighbors=rows("SELECT * FROM practice_duty WHERE dentist_id=%s AND publication_state='published' AND (%s::bigint IS NULL OR id<>%s) ORDER BY starts_at",[dentist,exclude,exclude])
    for old in neighbors:
        require(not (old['starts_at']<end and start<old['ends_at']),'牙医出诊时段重叠',409)
    before=max((d for d in neighbors if d['ends_at']<=start),key=lambda d:d['ends_at'],default=None);after=min((d for d in neighbors if d['starts_at']>=end),key=lambda d:d['starts_at'],default=None)
    for old,left,right,cfrom,cto in [(before,before['ends_at'] if before else start,start,before['clinic_id'] if before else clinic,clinic),(after,end,after['starts_at'] if after else end,clinic,after['clinic_id'] if after else clinic)]:
        if old and cfrom!=cto:
            rule=one('SELECT * FROM travel_rule WHERE from_clinic_id=%s AND to_clinic_id=%s AND valid_from<=%s AND (valid_to IS NULL OR valid_to>=%s)',[cfrom,cto,left.date(),right.date()]);require(rule,'缺少该方向的已确认跨店转场规则');require((right-left).total_seconds()>=rule['minimum_minutes']*60,'前后相邻出诊的跨店转场时间不足')
    employee=get('employee',dentist);require(employee and employee['employed_from']<=start.date() and (not employee['employed_to'] or employee['employed_to']>=end.date()),'牙医不在有效任职期间')
    current=get('clinic',clinic);require(current and current['opened_on']<=start.date() and (not current['closed_on'] or current['closed_on']>=end.date()),'门店不在有效营业期间')
    return dict(dentist_id=dentist,clinic_id=clinic,calendar_id=calendar['id'],starts_at=start,ends_at=end),skills

def duty_action(actor,b):
    actor.allow('business','manager');action=b.get('action','publish')
    if action in ('draft','publish-draft'):
        from .coordination import save_draft,publish_draft
        return save_draft(actor,b) if action=='draft' else publish_draft(actor,b)
    if action=='replace':
        actor.allow('manager','business');old=get('practice_duty',int(b['id']),True);version(old,b);actor.clinic_access(old['clinic_id']);require(old['publication_state']=='published','普通替代只能针对仍可履行的已发布出诊')
        affected=rows("SELECT * FROM appointment WHERE duty_id=%s AND resolution IN ('booked','arrived') ORDER BY id FOR UPDATE",[old['id']]);decisions={int(d['appointment_id']):d for d in b.get('appointment_decisions',[])}
        require(len(decisions)==len(b.get('appointment_decisions',[])) and set(decisions)<={a['id'] for a in affected},'逐患者处理记录重复或不属于该出诊')
        # The old state is changed only within this transaction. Any failed
        # validation below rolls the whole replacement back before publication.
        update('practice_duty',old['id'],dict(publication_state='superseded',row_version=old['row_version']+1))
        proposal=dict(b.get('new_duty',b));proposal['action']='publish';new=duty_action(actor,proposal);update('practice_duty',new['id'],dict(replaces_duty_id=old['id']))
        for a in affected:
            unchanged=a['dentist_id']==new['dentist_id'] and a['clinic_id']==new['clinic_id'] and new['starts_at']<=a['starts_at'] and a['ends_at']<=new['ends_at']
            if unchanged:
                update('appointment',a['id'],dict(duty_id=new['id'],row_version=a['row_version']+1));event(actor,a,'duty_replacement','患者约定要素未变，仅迁移有效出诊引用',original_duty_id=old['id'],replacement_duty_id=new['id'])
            else:
                d=decisions.get(a['id']);require(d and d.get('confirmation_basis') and d.get('replacement'),'变更患者约定要素前须逐项落实同意依据及新约，原安排仍可履行时不能留下待办',409)
                replacement=dict(d['replacement'],duty_id=new['id'],dentist_id=new['dentist_id'],clinic_id=new['clinic_id']);change(actor,dict(action='reschedule',id=a['id'],row_version=d.get('row_version'),reason=d['confirmation_basis'],initiator_kind='organisation',replacement=replacement))
        return dict(new,affected=[a['id'] for a in affected])
    if action=='travel-rule':
        actor.clinic_access(int(b['from_clinic_id']));return insert('travel_rule',dict(from_clinic_id=int(b['from_clinic_id']),to_clinic_id=int(b['to_clinic_id']),minimum_minutes=int(b['minimum_minutes']),valid_from=b['valid_from'],valid_to=b.get('valid_to') or None,confirmed_by=actor.employee,confirmation_basis=b['confirmation_basis']))
    if action=='stop':
        actor.allow('manager')
        d=get('practice_duty',int(b['id']),True);version(d,b);actor.clinic_access(d['clinic_id']);require(d['publication_state']=='published' and b.get('reason'),'仅能登记已发布出诊的真实停诊及原因')
        update('practice_duty',d['id'],dict(publication_state='stopped',stopped_at=timezone.now(),stop_reason=b['reason'],row_version=d['row_version']+1));affected=rows("SELECT * FROM appointment WHERE duty_id=%s AND resolution IN ('booked','arrived') FOR UPDATE",[d['id']])
        for a in affected:update('appointment',a['id'],dict(resolution='unfulfilled',row_version=a['row_version']+1));followup(actor,a);event(actor,a,'clinic_stop',b['reason'])
        return dict(get('practice_duty',d['id']),affected=[a['id'] for a in affected])
    data,skills=validate_duty(actor,b,lock=True)
    values=dict(**data,publication_state='published',confirmed_by=actor.employee,confirmed_at=timezone.now())
    if b.get('draft_id'):
        draft=get('practice_duty',int(b['draft_id']),True);require(draft and draft['publication_state'] in ('draft','pending_coordination'),'协调稿已变化',409)
        actor.clinic_access(draft['clinic_id']);require(draft['row_version']==b.get('draft_row_version'),'协调稿版本已变化',409)
        duty=update('practice_duty',draft['id'],dict(**values,row_version=draft['row_version']+1))
        execute('DELETE FROM duty_skill WHERE duty_id=%s',[duty['id']])
    else:duty=insert('practice_duty',dict(**values,row_version=1))
    for q in skills:insert('duty_skill',dict(duty_id=duty['id'],qualification_kind_id=q))
    return duty

def standard_action(actor,b):
    action=b.get('action','draft')
    if action in ('approve','reject'):
        actor.allow('director');s=get('treatment_standard',int(b['id']),True);require(s and s['approval_state']=='draft','只能批准草案')
        creator=one("SELECT a.account_id,u.employee_id FROM audit_event a JOIN user_account u ON u.id=a.account_id WHERE a.object_kind='UC10' AND a.business_reference=%s AND a.operation_name='draft' ORDER BY a.id LIMIT 1",[str(s['id'])]);require(creator and creator['employee_id']!=actor.employee,'不能批准本人提交或来源不明的项目标准')
        if action=='reject':
            require(str(b.get('reason','')).strip(),'退回草案须填写具体核实原因')
            return dict(update('treatment_standard',s['id'],dict(approval_state='rejected')),rejection_reason=b['reason'])
        if b.get('retire_previous'):
            execute("UPDATE treatment_standard SET approval_state='retired',valid_to=%s WHERE treatment_id=%s AND approval_state='approved' AND (valid_to IS NULL OR valid_to>%s)",[s['valid_from'],s['treatment_id'],s['valid_from']])
        return update('treatment_standard',s['id'],dict(approval_state='approved',approved_by=actor.employee,approved_at=timezone.now()))
    actor.allow('business')
    if action=='catalog':return insert('treatment_catalog',dict(treatment_code=b['treatment_code'],treatment_name=b['treatment_name'],is_available=True))
    if action=='disable':return update('treatment_catalog',int(b['id']),dict(is_available=False))
    treatment=int(b['treatment_id']);previous=one('SELECT MAX(revision_no) AS n FROM treatment_standard WHERE treatment_id=%s',[treatment])
    data={k:b[k] for k in ['treatment_name','unit_name','quantity_scale','unit_price','site_requirement','duration_minutes']};data.update(treatment_id=treatment,revision_no=(previous['n'] or 0)+1,valid_from=timestamp(b['valid_from']),valid_to=timestamp(b['valid_to']) if b.get('valid_to') else None,approval_state='draft')
    result=insert('treatment_standard',data)
    for q in b.get('qualification_kind_ids',[]):insert('standard_qualification',dict(standard_id=result['id'],qualification_kind_id=int(q)))
    return result

def resources_action(actor,b):
    from .resource_changes import resources_action as apply_change
    return apply_change(actor,b)

def accounts_action(actor,b):
    action=b.get('action','create');now=timezone.now()
    if action in ('disable','enable','password','unbind-wechat'):
        actor.allow('reception','business','director');account=get('user_account',int(b['id']),True);require(account,'账号不存在');require(account['id']!=actor.id,'本人账号状态请由其他有权人员核对')
        if actor.role=='reception':require(account['account_kind'] in ('patient','representative'),'前台仅能协助患者和代办账号',403)
        if account['account_kind']=='employee':
            elevated=one("SELECT s.id FROM account_scope s JOIN access_role r ON r.id=s.role_id WHERE s.account_id=%s AND r.role_code IN ('business','director','manager','finance') AND s.revoked_at IS NULL",[account['id']]);require(not elevated or actor.role=='director','该账号须由总部负责人管理',403)
        if action=='unbind-wechat':
            value=b.get('reason');require(isinstance(value,str),'请填写身份核实依据或工单号，最多160字')
            basis=value.strip();require(1<=len(basis)<=160,'请填写身份核实依据或工单号，最多160字')
            count=execute('UPDATE adc_auth.wechat_identity SET revoked_at=%s,revoked_by=%s,revocation_basis=%s WHERE account_id=%s AND revoked_at IS NULL',[now,actor.id,basis,account['id']]);require(count>0,'该账号没有有效微信绑定')
            return {'id':account['id'],'message':'微信绑定已解除，相关微信登录会话已失效'}
        if action=='password':require(len(b.get('password',''))>=12,'密码至少12位');result=update('user_account',account['id'],dict(password_hash=make_password(b['password'])))
        else:result=update('user_account',account['id'],dict(is_enabled=action=='enable'))
        public={k:v for k,v in result.items() if k!='password_hash'}
        if action=='disable' and account['employee_id']:
            pending=one('SELECT count(*) AS n FROM followup_task WHERE responsible_employee_id=%s AND closed_at IS NULL',[account['employee_id']])
            public.update(pending_followup_count=pending['n'],responsibilities_preserved=True,handover_required=pending['n']>0)
        return public
    if action=='grant':
        actor.allow('reception','business','director');role=get('access_role',int(b['role_id']));require(role,'岗位不存在')
        account=get('user_account',int(b['account_id']),True);require(account and account['is_enabled'],'账号不存在或已停用')
        require(account['id']!=actor.id,'不能为本人提升或追加岗位权限',403)
        scope=b['scope_kind'];code=role['role_code']
        if code=='patient':
            require(account['account_kind']=='patient' and scope=='self' and int(b.get('patient_id') or 0)==account['patient_id'],'患者岗位必须关联本人患者及本人范围',403)
        elif code=='representative':
            require(account['account_kind']=='representative' and scope=='authorized_patient' and b.get('patient_id'),'代办岗位必须关联具体获授权患者',403)
            require(one("SELECT id FROM patient_authority WHERE authorized_account_id=%s AND patient_id=%s AND revoked_at IS NULL AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())",[account['id'],int(b['patient_id'])]),'没有该患者当前有效的核实授权',403)
        else:
            actor.allow('director')
            require(account['account_kind']=='employee' and account['employee_id'] and scope in ('clinic','group'),'职员岗位与账号主体或范围不符',403)
            if code=='dentist':require(get('dentist',account['employee_id']),'牙医岗位必须关联牙医档案',403)
            if code in ('manager','reception'):require(scope=='clinic','主管及接待岗位须逐门店授权，跨店办理请另授相应门店范围',403)
        if actor.role=='reception':require(code in ('patient','representative'),'前台不能授予职员岗位',403)
        if scope=='clinic':require(b.get('clinic_id') and get('clinic',int(b['clinic_id'])),'请选择真实门店')
        require(not one('SELECT id FROM account_scope WHERE account_id=%s AND role_id=%s AND scope_kind=%s AND clinic_id IS NOT DISTINCT FROM %s AND patient_id IS NOT DISTINCT FROM %s AND revoked_at IS NULL',[account['id'],role['id'],scope,int(b['clinic_id']) if b.get('clinic_id') else None,int(b['patient_id']) if b.get('patient_id') else None]),'该岗位与范围已经生效')
        if actor.scope['scope_kind']!='group' and code not in ('patient','representative'):require(b.get('scope_kind')=='clinic' and int(b['clinic_id'])==actor.clinic,'不能授予超出本人范围的权限',403)
        return insert('account_scope',dict(account_id=int(b['account_id']),role_id=role['id'],clinic_id=int(b['clinic_id']) if b.get('clinic_id') else None,patient_id=int(b['patient_id']) if b.get('patient_id') else None,scope_kind=b['scope_kind'],granted_by=actor.id,granted_at=now))
    if action=='revoke':
        actor.allow('director','business');s=get('account_scope',int(b['id']),True);require(s,'岗位授权不存在');r=get('access_role',s['role_id']);require(actor.role=='director' or r['role_code'] not in ('director','business','finance','manager'),'无权撤销该岗位',403);return update('account_scope',s['id'],dict(revoked_at=now))
    actor.allow('reception','business','director')
    kind=b['account_kind'];require(kind in ('patient','representative','employee'),'登录主体类型不符')
    if actor.role=='reception':require(kind in ('patient','representative'),'前台仅可开通患者及代办账号',403)
    require(len(b.get('password',''))>=12,'密码至少12位')
    account=insert('user_account',dict(login_name=b['login_name'],password_hash=make_password(b['password']),is_enabled=True,account_kind=kind,employee_id=int(b['employee_id']) if kind=='employee' else None,patient_id=int(b['patient_id']) if kind=='patient' else None,display_name=b['display_name'],created_at=now))
    if kind=='patient':
        role=one("SELECT id FROM access_role WHERE role_code='patient'");insert('account_scope',dict(account_id=account['id'],role_id=role['id'],patient_id=account['patient_id'],scope_kind='self',granted_by=actor.id,granted_at=now))
    return {k:v for k,v in account.items() if k!='password_hash'}
