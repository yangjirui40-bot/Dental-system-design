from dataclasses import dataclass
from datetime import datetime, timezone
from django.core import signing
from django.contrib.auth.hashers import check_password, make_password
from .db import one, rows, get

class BusinessError(Exception):
    def __init__(self, message, status=422, code='business_rule'):
        self.message, self.status, self.code = message, status, code

def require(condition, message, status=422):
    if not condition: raise BusinessError(message, status)

ROLE_CODES = {'patient': '患者', 'representative': '监护人或授权代办人', 'reception': '前台接待员',
 'dentist': '牙医', 'manager': '诊所主管', 'business': '总部业务人员', 'finance': '总部财务人员', 'director': '总部负责人'}

PATIENT_ROLES = frozenset(('patient', 'representative'))
STAFF_ROLES = frozenset(ROLE_CODES) - PATIENT_ROLES

def client_surface(value):
    require(value in ('patient', 'staff'), '客户端入口标识无效', 422)
    return value

def account_surface(account):
    return 'staff' if account['account_kind']=='employee' else 'patient'

def surface_scopes(account_id, surface):
    roles=PATIENT_ROLES if client_surface(surface)=='patient' else STAFF_ROLES
    return [scope for scope in scopes(account_id) if scope['role_code'] in roles]

@dataclass
class Actor:
    account: dict
    scope: dict
    external_binding_id: int|None = None
    surface: str|None = None
    @property
    def id(self): return self.account['id']
    @property
    def employee(self): return self.account['employee_id']
    @property
    def role(self): return self.scope['role_code']
    @property
    def clinic(self): return self.scope['clinic_id']
    def allow(self, *roles): require(self.role in roles, '当前岗位无权办理此操作', 403)
    def clinic_access(self, clinic_id):
        require(self.scope['scope_kind'] == 'group' or self.clinic == int(clinic_id), '门店超出授权范围', 403)
    def patient_access(self, patient_id, permission='all'):
        patient_id = int(patient_id)
        if self.role == 'patient': require(self.account['patient_id'] == patient_id, '只允许访问本人资料', 403)
        elif self.role == 'representative':
            authority = one("SELECT * FROM patient_authority WHERE patient_id=%s AND authorized_account_id=%s AND revoked_at IS NULL AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now()) AND permission_scope IN (%s,'all')", [patient_id, self.id, permission])
            require(authority, '未取得该患者当前事项的有效授权', 403)
            require(self.scope['scope_kind']=='authorized_patient' and self.scope['patient_id']==patient_id, '请切换至该患者的有效授权范围', 403)
        elif self.role == 'dentist':
            # Cross-clinic authorisation never grants unrelated patient access.
            linked = one('SELECT id FROM appointment WHERE patient_id=%s AND dentist_id=%s UNION SELECT id FROM treatment_plan WHERE patient_id=%s AND created_by=%s LIMIT 1', [patient_id,self.employee,patient_id,self.employee])
            require(linked, '患者不在本人接诊或负责方案的范围内', 403)
        elif self.scope['scope_kind'] != 'group':
            linked = one('SELECT id FROM appointment WHERE patient_id=%s AND clinic_id=%s LIMIT 1', [patient_id,self.clinic])
            require(linked, '患者不在当前岗位的服务范围内', 403)

def scopes(account_id):
    return rows("""SELECT s.*,r.role_code,r.role_name,c.clinic_name,p.full_name AS authorized_patient_name
      FROM account_scope s JOIN access_role r ON r.id=s.role_id
      LEFT JOIN clinic c ON c.id=s.clinic_id LEFT JOIN patient p ON p.id=s.patient_id
      WHERE s.account_id=%s AND s.revoked_at IS NULL AND (r.role_code<>'representative' OR EXISTS
        (SELECT 1 FROM patient_authority a WHERE a.authorized_account_id=s.account_id AND a.patient_id=s.patient_id
         AND a.revoked_at IS NULL AND a.valid_from<=now() AND (a.valid_to IS NULL OR a.valid_to>now()))) ORDER BY s.id""", [account_id])

def authenticate(request):
    raw = request.headers.get('Authorization','')
    require(raw.startswith('Bearer '), '请先登录', 401)
    try:
        payload = signing.loads(raw[7:], salt='adc-access', max_age=8*3600)
        require(not payload.get('external_binding'), '登录已失效，请重新登录',401)
    except signing.BadSignature:
        try: payload = signing.loads(raw[7:], salt='adc-wechat-access-v1', max_age=8*3600)
        except signing.BadSignature: raise BusinessError('登录已失效，请重新登录',401)
        require(payload.get('external_binding'), '登录已失效，请重新登录',401)
    account = get('user_account', payload['account'])
    require(account and account['is_enabled'], '账号不可用',401)
    require(payload.get('credential')==signing.salted_hmac('adc-credential',account['password_hash']).hexdigest(), '登录已失效',401)
    if payload.get('external_binding'):
        binding=one('SELECT id FROM adc_auth.wechat_identity WHERE id=%s AND account_id=%s AND revoked_at IS NULL',[payload['external_binding'],account['id']])
        require(binding,'微信绑定已解除，请重新核实账号登录',401)
    surface=client_surface(payload.get('surface') or ('patient' if payload.get('external_binding') else account_surface(account)))
    if request.headers.get('X-ADC-Surface'):
        require(request.headers['X-ADC-Surface']==surface, '当前会话不属于此入口，请重新登录', 403)
    available = surface_scopes(account['id'],surface)
    selected = next((s for s in available if s['id']==payload['scope']), None)
    if not selected:raise BusinessError('岗位或患者事项授权已撤销，请重新核实',403,'scope_revoked')
    return Actor(account, selected, payload.get('external_binding'),surface)

def token(account, scope_id, external_binding_id=None, surface=None):
    surface=client_surface(surface or ('patient' if external_binding_id else account_surface(account)))
    require(not external_binding_id or surface=='patient','微信患者入口不能签发工作人员会话',403)
    require(any(s['id']==scope_id for s in surface_scopes(account['id'],surface)),'身份不属于当前服务入口',403)
    payload={'account':account['id'],'scope':scope_id,'surface':surface,'credential':signing.salted_hmac('adc-credential',account['password_hash']).hexdigest()}
    if external_binding_id:payload['external_binding']=external_binding_id
    return signing.dumps(payload,salt='adc-wechat-access-v1' if external_binding_id else 'adc-access')
