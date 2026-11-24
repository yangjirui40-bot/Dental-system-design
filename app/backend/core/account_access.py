"""User-requested account access extension; business roles remain in account_scope."""
import hashlib,json,logging,re,uuid
from datetime import date,timedelta
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.hashers import make_password,check_password
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .db import one,rows,execute,insert,update,get,business_no
from .http import endpoint
from .security import require,BusinessError,scopes,token,surface_scopes
from .patient_profile import emergency_details,save_emergency,declaration

logger=logging.getLogger(__name__)
IDENTITY_SALT='adc-wechat-identity-v1'
RESET_SALT='adc-password-recovery-v1'

def appid():return settings.WECHAT_APP_ID

def ticket_read(value,salt):
    try:payload=signing.loads(str(value or ''),salt=salt,max_age=300)
    except (signing.BadSignature,ValueError,TypeError):raise BusinessError('验证已失效，请重新进行微信验证',401)
    require(isinstance(payload,dict) and payload.get('appid')==appid(),'微信验证来源不符',401)
    require(re.fullmatch(r'[0-9a-f]{64}',str(payload.get('subject',''))),'微信验证无效',401)
    return payload

def exchange_code(code):
    require(settings.WECHAT_APP_SECRET,'微信登录尚未配置完成，请使用账号密码登录',503)
    require(isinstance(code,str) and 5<=len(code)<=256,'请重新点击微信登录',401)
    query=urlencode(dict(appid=appid(),secret=settings.WECHAT_APP_SECRET,js_code=code,grant_type='authorization_code'))
    try:
        with urlopen('https://api.weixin.qq.com/sns/jscode2session?'+query,timeout=8) as response:data=json.load(response)
    except (URLError,OSError,TimeoutError,ValueError):raise BusinessError('微信验证服务暂时不可达，请稍后重试',503) from None
    require(isinstance(data,dict),'微信验证服务返回异常，请重试',503)
    if data.get('errcode'):
        code=data['errcode'];logger.warning('wechat_code2session_rejected errcode=%s',code)
        if code in (40029,40163):raise BusinessError('微信验证已过期，请重新点击微信登录',401)
        raise BusinessError('微信登录暂不可用，请使用账号密码或稍后重试',503)
    subject=data.get('openid');require(isinstance(subject,str) and 6<=len(subject)<=128,'微信验证未完成，请重试',503)
    # High-entropy provider identifier is pseudonymised; no session_key is kept.
    return hashlib.sha256((appid()+'\0'+subject).encode()).hexdigest()

def identity_list(subject):
    accounts=rows('SELECT DISTINCT a.id,a.login_name,a.display_name,a.account_kind FROM adc_auth.wechat_identity w JOIN public.user_account a ON a.id=w.account_id WHERE w.appid=%s AND w.subject_hash=%s AND w.revoked_at IS NULL AND a.is_enabled ORDER BY a.id',[appid(),subject])
    accounts=[a for a in accounts if a['account_kind'] in ('patient','representative')]
    for account in accounts:account['scopes']=surface_scopes(account['id'],'patient')
    return accounts

def choice(subject):
    accounts=identity_list(subject)
    return {'state':'choose_identity' if accounts else 'register_or_bind','identity_ticket':signing.dumps({'appid':appid(),'subject':subject},salt=IDENTITY_SALT),'identities':accounts,'expires_in':300}

def audit(account,operation,fields):
    insert('audit_event',dict(account_id=account['id'],object_kind='AUTH',business_reference=str(account['id']),operation_name=operation,changed_fields=fields,result_digest=hashlib.sha256((operation+':'+str(account['id'])).encode()).hexdigest(),occurred_at=timezone.now(),request_id=uuid.uuid4()))

def subject_lock(subject):execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',['adc-wechat:'+subject])

def bind_identity(subject,account):
    existing=one('SELECT * FROM adc_auth.wechat_identity WHERE account_id=%s AND appid=%s AND revoked_at IS NULL FOR UPDATE',[account['id'],appid()])
    if existing:
        require(existing['subject_hash']==subject,'此账号已绑定其他微信，请联系有权人员核实换绑',409)
        return existing
    return one('INSERT INTO adc_auth.wechat_identity(account_id,appid,subject_hash,created_at,last_used_at) VALUES(%s,%s,%s,%s,%s) RETURNING *',[account['id'],appid(),subject,timezone.now(),timezone.now()])

def verified_mapping(payload,account_id,lock=False):
    account=get('user_account',int(account_id),lock)
    require(account and account['is_enabled'],'账号不可用，请联系门店核实',401)
    binding=one('SELECT * FROM adc_auth.wechat_identity WHERE account_id=%s AND appid=%s AND subject_hash=%s AND revoked_at IS NULL'+(' FOR UPDATE' if lock else ''),[account['id'],appid(),payload['subject']])
    require(binding,'该微信未关联所选账号，请重新选择身份',403)
    require(account['account_kind'] in ('patient','representative'),'微信小程序仅提供患者及已授权代办服务，工作人员请使用诊所管理系统',403)
    return account,binding

def consent(body):require(body.get('privacy_accepted') is True,'请先阅读并同意隐私说明')

def password_value(body):
    value=body.get('password','');require(isinstance(value,str) and 12<=len(value)<=128 and value.strip(),'密码须为12至128个字符')
    return value

@endpoint
def options(request,b):
    return {'wechat_enabled':bool(settings.WECHAT_APP_SECRET),'wechat_appid':appid(),'password_login':True,'patient_registration':True,'representative_registration':True,'staff_registration':False,'staff_portal':'https://api.yjr-adc-demo.xyz/','wechat_surface':'patient','support_email':'2684077388@qq.com','allergy_substances':rows('SELECT id,substance_name FROM allergy_substance ORDER BY id')}

@csrf_exempt
@endpoint
def wechat(request,b):
    require(request.method=='POST','请使用POST',405);consent(b)
    return choice(exchange_code(b.get('code')))

@csrf_exempt
@endpoint
def select(request,b):
    require(request.method=='POST','请使用POST',405);payload=ticket_read(b.get('identity_ticket'),IDENTITY_SALT)
    with transaction.atomic():
        account,binding=verified_mapping(payload,b.get('account_id'),True)
        available=surface_scopes(account['id'],'patient');selected=next((s for s in available if s['id']==int(b.get('scope_id') or 0)),None)
        require(selected,'该身份尚未授权或授权已撤销，请联系门店核实',403)
        execute('UPDATE adc_auth.wechat_identity SET last_used_at=%s WHERE id=%s',[timezone.now(),binding['id']]);audit(account,'auth.wechat_login','identity_binding,active_scope')
        return {'token':token(account,selected['id'],binding['id']),'account':{k:account[k] for k in ['id','login_name','display_name','account_kind','patient_id']},'scope':selected,'scopes':available}

@csrf_exempt
@endpoint
def bind(request,b):
    require(request.method=='POST','请使用POST',405);payload=ticket_read(b.get('identity_ticket'),IDENTITY_SALT)
    with transaction.atomic():
        subject_lock(payload['subject'])
        account=one('SELECT * FROM user_account WHERE login_name=%s FOR UPDATE',[str(b.get('login_name',''))])
        matched=check_password(str(b.get('password','')),account['password_hash'] if account else make_password('unavailable-identity'))
        require(account and account['is_enabled'] and matched,'账号或密码不正确',401)
        require(account['account_kind'] in ('patient','representative'),'工作人员请使用诊所管理系统，不能在患者微信入口绑定工作账号',403)
        bind_identity(payload['subject'],account);audit(account,'auth.wechat_bind','identity_binding')
        return choice(payload['subject'])

@csrf_exempt
@endpoint
def register(request,b):
    require(request.method=='POST','请使用POST',405);consent(b)
    require(b.get('client_surface','patient')=='patient','诊所管理端不开放自助注册，请由有权人员开通工作人员账号',403)
    kind=b.get('account_kind');require(kind in ('patient','representative'),'工作人员须绑定已开通并授权的工作账号，不能自行取得岗位权限')
    payload=ticket_read(b['identity_ticket'],IDENTITY_SALT) if b.get('identity_ticket') else None
    name=str(b.get('full_name','')).strip();require(1<=len(name)<=100,'请填写本人姓名')
    login_name=str(b.get('login_name','')).strip()
    if not login_name and payload:login_name='wx_'+payload['subject'][:24]
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{2,79}',login_name),'账号须为3至80位字母、数字、点、下划线、@或短横线')
    password=make_password(password_value(b)) if b.get('password') or not payload else make_password(None)
    now=timezone.now()
    with transaction.atomic():
        if payload:
            subject_lock(payload['subject'])
            accounts=identity_list(payload['subject'])
            if any(a['account_kind']==kind for a in accounts):return choice(payload['subject'])
        require(not one('SELECT id FROM user_account WHERE login_name=%s',[login_name]),'账号已存在，请登录或使用找回密码',409)
        patient=None
        if kind=='patient':
            emergency=emergency_details(b);require(emergency,'请填写紧急联系人姓名、电话及关系')
            state=b.get('allergy_declaration','unknown');initial_allergy=None
            if state=='reported':
                initial_allergy=get('allergy_substance',int(b.get('allergy_substance_id') or 0));require(initial_allergy,'已申报过敏须选择具体过敏物质')
                require(str(b.get('allergy_reaction','')).strip(),'请填写过敏反应；不清楚时请明确填写“不清楚”')
            else:declaration(state)
            try:birth=date.fromisoformat(str(b.get('birth_date','')))
            except ValueError:raise BusinessError('请填写有效出生日期') from None
            today=timezone.localdate();require(today-timedelta(days=130*366)<=birth<=today,'出生日期超出有效范围')
            age=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day));require(age>=14,'未满14周岁请由监护人联系门店核实开通')
            phone=str(b.get('phone','')).strip();address=str(b.get('billing_address','')).strip();email=str(b.get('email','')).strip()
            require(7<=len(phone)<=40 and re.fullmatch(r'[+0-9()\s-]+',phone),'请填写有效联系电话')
            require(1<=len(address)<=160,'请填写通讯地址，暂不提供时请明确填写“暂不提供”')
            if email:
                try:validate_email(email)
                except ValidationError:raise BusinessError('邮箱格式不正确') from None
            # Serialize an exact demographic match even while the first patient's
            # row is uncommitted. This does not merge or identify existing people.
            execute("SELECT pg_advisory_xact_lock(hashtextextended(jsonb_build_array('adc-patient-registration',lower(%s),%s::text,%s::text)::text,0))",[name,birth,phone])
            require(not one('SELECT id FROM patient WHERE lower(full_name)=lower(%s) AND birth_date=%s AND phone=%s',[name,birth,phone]),'资料可能已有档案，请绑定原账号或联系门店核实，不会自动合并或接管',409)
            patient=insert('patient',dict(account_no=business_no('P'),full_name=name,birth_date=birth,sex_code=b.get('sex_code') or 'unknown',billing_address=address,phone=phone,email=email or None,allergy_declaration=state,row_version=1,created_at=now))
        account=insert('user_account',dict(login_name=login_name,password_hash=password,is_enabled=True,account_kind=kind,patient_id=patient['id'] if patient else None,display_name=name,created_at=now))
        if patient:
            save_emergency(patient['id'],emergency,account['id'],None,now)
            insert('patient_revision',dict(**{k:patient[k] for k in ['full_name','birth_date','sex_code','billing_address','phone','email']},patient_id=patient['id'],revision_no=1,change_reason='本人首次登记',recorded_account_id=account['id'],recorded_at=now))
            if initial_allergy:
                item=insert('patient_allergy',dict(patient_id=patient['id'],substance_id=initial_allergy['id'],first_reported_at=now))
                insert('allergy_revision',dict(allergy_id=item['id'],revision_no=1,reaction_description=str(b['allergy_reaction']).strip(),reporter_name=name,report_source='本人注册申报，尚待牙医核实',verification_result='reported',recorded_account_id=account['id'],recorded_at=now))
            role=one("SELECT id FROM access_role WHERE role_code='patient'")
            require(role,'账号服务尚未初始化，请联系管理员',503)
            insert('account_scope',dict(account_id=account['id'],role_id=role['id'],patient_id=patient['id'],scope_kind='self',granted_by=account['id'],granted_at=now))
        if payload:bind_identity(payload['subject'],account)
        audit(account,'auth.register_'+kind,'account_kind,identity_binding' if payload else 'account_kind')
        if payload:return choice(payload['subject'])
        return {'state':'registered' if patient else 'authorization_pending','login_name':account['login_name'],'message':'账号已建立，请登录' if patient else '代办账号已建立，请由门店核实患者及授权事项后使用'}

@csrf_exempt
@endpoint
def recovery(request,b):
    require(request.method=='POST','请使用POST',405);payload=ticket_read(b.get('identity_ticket'),IDENTITY_SALT)
    with transaction.atomic():
        account,binding=verified_mapping(payload,b.get('account_id'),True)
        credential=signing.salted_hmac('adc-recovery-credential',account['password_hash']).hexdigest()
        value=signing.dumps(dict(appid=appid(),subject=payload['subject'],account=account['id'],binding=binding['id'],credential=credential),salt=RESET_SALT)
        return {'reset_ticket':value,'expires_in':300,'login_name':account['login_name']}

@csrf_exempt
@endpoint
def reset_password(request,b):
    require(request.method=='POST','请使用POST',405);payload=ticket_read(b.get('reset_ticket'),RESET_SALT);password=password_value(b)
    with transaction.atomic():
        account,binding=verified_mapping(payload,payload.get('account'),True)
        require(binding['id']==payload.get('binding'),'微信绑定已变更，请重新验证',401)
        credential=signing.salted_hmac('adc-recovery-credential',account['password_hash']).hexdigest()
        require(credential==payload.get('credential'),'找回凭据已使用或账号口令已变更，请重新验证',401)
        update('user_account',account['id'],{'password_hash':make_password(password)});audit(account,'auth.password_reset','credential_version')
        return {'state':'password_reset','login_name':account['login_name'],'message':'密码已重设，原登录已失效，请重新登录'}
