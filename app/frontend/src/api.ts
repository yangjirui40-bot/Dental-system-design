import { reactive } from 'vue'
let defaultSurface='staff'
// #ifdef MP-WEIXIN
defaultSurface='patient'
// #endif
export const clientSurface=(import.meta.env.VITE_APP_SURFACE||defaultSurface) as 'patient'|'staff'
const tokenStorageKey='adc-'+clientSurface+'-token'
export const session=reactive({token:uni.getStorageSync(tokenStorageKey)||'',scope:null as any})
export const clientVersion=import.meta.env.VITE_APP_VERSION||'1.5.2'
const origin=(import.meta.env.VITE_API_BASE||'').replace(/\/$/,'')
let useCloud=false
// #ifdef MP-WEIXIN
useCloud=import.meta.env.VITE_NETWORK_TRANSPORT==='wechat-cloud'
// #endif
let cloudInitialised=false
const cloudEnvironment=import.meta.env.VITE_WECHAT_CLOUD_ENV||''
export class ApiError extends Error{constructor(message:string,public status:number){super(message);this.name='ApiError'}}
const teachingPrefix='teaching:'
export function inTeachingSession(){return session.token.startsWith(teachingPrefix)}
export function request(path:string, data?:any, key?:string, teachingLogin=false):Promise<any>{
 // A late response for a previous identity must never clear a newer login.
 // Invalid registration/WeChat proofs are form errors, not session revocation.
 const publicAuth=/^\/api\/auth\/(?:login|options|register|wechat(?:\/bind|\/select)?|recovery|reset-password)(?:\?|$)/.test(path)
 if(publicAuth&&data&&typeof data==='object')data={...data,client_surface:clientSurface}
 const sessionAtRequest=publicAuth?'':session.token
 const teaching=teachingLogin || (!publicAuth && sessionAtRequest.startsWith(teachingPrefix))
 const requestToken=teaching && !publicAuth ? sessionAtRequest.slice(teachingPrefix.length) : sessionAtRequest
 if(teaching && path.startsWith('/api/'))path='/api/teaching/'+path.slice(5)
 return new Promise((resolve,reject)=>{
  const receive=(res:any)=>{
   if(!res||!Number.isInteger(res.statusCode)||res.data===undefined){reject(new ApiError('服务响应无效，请稍后重试。',502));return}
   const body=res.data
   if(teaching && body && typeof body.token==='string')body.token=teachingPrefix+body.token
   if(res.statusCode>=200&&res.statusCode<300)resolve(body)
   else {if(!publicAuth&&requestToken&&sessionAtRequest===session.token&&(res.statusCode===401||body?.error==='scope_revoked')){session.token='';uni.removeStorageSync(tokenStorageKey);uni.$emit('adc:authentication-lost',body?.message||'登录已失效，请重新核实身份')}reject(new ApiError(body?.message||(res.statusCode===429?'操作过于频繁，请稍后再试':'服务暂时不可用'),res.statusCode))}
  }
  if(useCloud){
   // #ifdef MP-WEIXIN
   const cloud=(globalThis as any).wx?.cloud
   if(!cloud||cloudEnvironment!=='dental-d8gj2dy3mb506dfdc'){reject(new ApiError('微信联调入口不可用，请更新微信或联系管理员。',0));return}
   try{
    if(!cloudInitialised){cloud.init({env:cloudEnvironment,traceUser:false});cloudInitialised=true}
    cloud.callFunction({name:'adcNetworkGateway',data:{path,method:data===undefined?'GET':'POST',...(data===undefined?{}:{data}),token:requestToken,idempotencyKey:key||''},success:(res:any)=>receive(res.result),fail:()=>reject(new ApiError('微信服务连接暂时失败，请稍后重试。',0))})
   }catch{reject(new ApiError('微信服务连接暂时失败，请稍后重试。',0))}
   // #endif
   return
  }
  uni.request({url:origin+path,method:data===undefined?'GET':'POST',data,timeout:15000,firstIpv4:true,enableHttp2:false,enableQuic:false,enableCache:false,enableHttpDNS:false,header:{'Content-Type':'application/json','X-ADC-Surface':clientSurface,...(requestToken?{Authorization:'Bearer '+requestToken}:{}),...(key?{'Idempotency-Key':key}:{})},success:receive,fail(reason:any){const detail=String(reason?.errMsg||'network unavailable').replace(/(token|password|secret)=[^\s&]+/gi,'$1=[redacted]').slice(0,220);const code=reason?.errno??reason?.errCode;reject(new ApiError('无法连接诊所服务。'+detail+(code===undefined?'':'（编号 '+code+'）'),0))}})
 })
}
export function uuid(){return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.floor(Math.random()*16);return(c==='x'?r:(r&3)|8).toString(16)})}
export function clearToken(){session.token='';session.scope=null;uni.removeStorageSync(tokenStorageKey);uni.removeStorageSync('adc-token')}
export function saveToken(value:string){session.token=value;uni.setStorageSync(tokenStorageKey,value);uni.removeStorageSync('adc-token')}
export async function login(login_name:string,password:string,teaching=false){const r=await request('/api/auth/login',{login_name,password},undefined,teaching);saveToken(r.token);return r}
export async function switchScope(scope_id:number){const r=await request('/api/auth/scope',{scope_id});saveToken(r.token);session.scope=r.scope;return r}
export const statusNames:Record<string,string>={pending_coordination:'待协调',performed:'已实施',interrupted:'部分实施后中止',deferred:'暂缓未实施',emergency:'紧急联系',guardian:'监护人',agent:'授权代办',booking:'预约办理',profile:'资料维护',invoices:'结算查询',consent:'临床同意',all:'全部明确授权事项',unknown:'尚未核实',denied:'本人否认已知过敏',female:'女',male:'男',self_service:'待自助接续',contacted:'已联系',no_response:'未响应',needs_assistance:'需协助',retired:'已结束生效',rejected:'未通过核实',booked:'已确认',arrived:'已报到',seen:'已接诊',cancelled:'已取消',rescheduled:'已改期',unfulfilled:'机构停诊待接续',no_show:'已核实未到',left_unseen:'到店未接诊',ready:'可办理',waiting:'待前序／临床确认',completed:'已完成',paused:'已暂停',terminated:'已终止',draft:'草稿',signed:'已签署',current:'有效',pending:'待核实',published:'已发布',stopped:'已停诊',superseded:'已被替代',approved:'已批准',verified:'已核实',reported:'已申报',refuted:'已排除',active:'可用',maintenance:'维护中',inactive:'已停用',provisional:'暂算',confirmed:'已确认',stale:'待重核',disputed:'存在异议',patient:'患者',representative:'代办人',employee:'职员',group:'集团范围',clinic:'门店范围',self:'本人',authorized_patient:'授权患者',supplies:'医疗用品',operating:'运营费用'}
export function format(value:any){if(value===null||value===undefined)return '—';if(typeof value==='boolean')return value?'是':'否';return statusNames[value]||String(value).replace('T',' ').replace(/\+00:00$/,' UTC')}
export function dateTime(value:string){return new Date(value).toLocaleString('zh-CN',{hour12:false})}
