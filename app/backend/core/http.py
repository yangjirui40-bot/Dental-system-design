import json, logging, uuid, hashlib
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.db import IntegrityError, DataError, OperationalError, transaction
from .db import serial, one, insert, update
from .security import BusinessError, require
logger = logging.getLogger(__name__)

def response(data, status=200): return JsonResponse(data, safe=False, status=status, json_dumps_params={'default':serial,'ensure_ascii':False})

class ApiMiddleware:
    def __init__(self, get_response): self.get_response=get_response
    def __call__(self, request):
        if request.method=='OPTIONS': result=HttpResponse(status=204)
        else: result=self.get_response(request)
        origin=request.headers.get('Origin')
        if origin in settings.CORS_ORIGINS:
            result['Access-Control-Allow-Origin']=origin
            result['Vary']='Origin'
            result['Access-Control-Allow-Headers']='Authorization, Content-Type, Idempotency-Key, X-ADC-Surface'
            result['Access-Control-Allow-Methods']='GET, POST, OPTIONS'
        result['Cache-Control']='no-store'
        return result

def endpoint(fn):
    def wrapped(request, **kwargs):
        try:
            body=json.loads(request.body or b'{}')
            require(isinstance(body,dict),'请求内容必须为对象',400)
            return response(fn(request,body,**kwargs))
        except BusinessError as e:
            if e.status==403 and request.path=='/api/use-cases/UC16':
                # Record rejected privilege changes after the mutation transaction rolls back.
                from .security import authenticate
                from django.utils import timezone
                try:
                    actor=authenticate(request)
                    with transaction.atomic():
                        insert('audit_event',dict(account_id=actor.id,acting_role_id=actor.scope['role_id'],scope_clinic_id=actor.clinic,object_kind='UC16',business_reference=str(body.get('account_id') or body.get('id') or 'UC16')[:40],operation_name=('denied.'+str(body.get('action','save')))[:40],changed_fields=','.join(sorted(k for k in body if k!='password'))[:2000],result_digest=hashlib.sha256(e.message.encode()).hexdigest(),occurred_at=timezone.now(),request_id=uuid.uuid4()))
                except (BusinessError,ValueError):pass
            return response({'error':e.code,'message':e.message},e.status)
        except (ValueError,KeyError,TypeError) as e:
            logger.info('Rejected invalid input: %s',type(e).__name__)
            return response({'error':'invalid_input','message':'字段缺失或格式不正确，请核对输入'},400)
        except IntegrityError:
            return response({'error':'conflict','message':'资料版本、时段占用或关联数据发生冲突，请刷新后重试'},409)
        except DataError:
            return response({'error':'invalid_input','message':'字段长度、数值范围或数据格式不符合要求'},400)
        except OperationalError as e:
            if getattr(e.__cause__,'sqlstate','') in ('40P01','40001'):
                return response({'error':'concurrent_conflict','message':'并发办理发生冲突，原记录已保留，请使用原请求凭据重试'},409)
            raise
    wrapped.__name__=fn.__name__
    return wrapped

def mutation(actor, code, request, body, action):
    for field in ['identity_confirmed','allergy_confirmed','is_open','approved','supplies_complete','operating_complete','clinical_confirmed','retire_previous','confirm_existing_revision','impact_acknowledged']:
        if field in body:require(isinstance(body[field],bool),'确认字段必须为布尔值',400)
    key=request.headers.get('Idempotency-Key')
    require(key,'缺少请求凭据，请重新提交',400)
    try: key=uuid.UUID(key)
    except ValueError: raise BusinessError('请求凭据格式错误',400)
    fingerprint=hashlib.sha256(json.dumps({'body':body,'path':request.path,'scope':actor.scope['id']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with transaction.atomic():
        # Serialize equal credentials even before a row exists, across all API workers.
        one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',[str(key)])
        previous=one('SELECT * FROM idempotency_request WHERE id=%s FOR UPDATE',[key])
        if previous:
            require(previous['account_id']==actor.id and previous['use_case_code']==code and previous['request_fingerprint']==fingerprint,'请求凭据已被其他内容使用',409)
            return {'id':previous['result_reference'],'replayed':True}
        if code in ('UC03','UC04','UC05','UC06','UC08','UC09','UC11','UC12','UC13','UC15'):
            # Financial source changes and quarter confirmation use the same
            # transaction lock. A correction cannot miss a just-confirmed report.
            one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',['adc:financial-sources'])
        from django.utils import timezone
        insert('idempotency_request',dict(id=key,account_id=actor.id,use_case_code=code,request_fingerprint=fingerprint,processing_result='processing',created_at=timezone.now()))
        from .auditing import before_version,after_version
        prior=before_version(actor,code,body)
        result=action();ref=str(result.get('id') or result.get('reference') or code)
        require(len(ref)<=40,'结果引用超过约束')
        update('idempotency_request',key,dict(processing_result='completed',result_reference=ref,completed_at=timezone.now()))
        fields=','.join(sorted(k for k in body if k not in ('password','clinical_note','treatments')))
        if code=='UC10' and body.get('action')=='reject':fields=json.dumps({'fields':fields.split(','),'decision_reason':str(body['reason'])[:1000]},ensure_ascii=False)
        scope_clinic=actor.clinic or result.get('clinic_id') or (result.get('id') if code=='UC07' and body.get('action')=='save' else None)
        insert('audit_event',dict(account_id=actor.id,acting_role_id=actor.scope['role_id'],scope_clinic_id=scope_clinic,object_kind=code,business_reference=ref,operation_name=body.get('action','save')[:40],previous_version_reference=prior,next_version_reference=after_version(code,body,result),changed_fields=fields[:2000],result_digest=hashlib.sha256(json.dumps(result,default=serial,sort_keys=True).encode()).hexdigest(),occurred_at=timezone.now(),request_id=key))
        return result
