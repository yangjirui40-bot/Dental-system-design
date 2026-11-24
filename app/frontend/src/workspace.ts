import { reactive, computed } from 'vue'
import { inTeachingSession, request, login, switchScope, session,saveToken,clearToken,clientSurface } from './api'

export type Row = Record<string, any>
export type Workspace = { teaching?:boolean; account: Row; scope: Row; scopes: Row[]; menu: {code:string;name:string}[]; resources: Record<string,Row[]>; server_time:string;capabilities?:Record<string,boolean>;application_surface?:'patient'|'staff' }
export const work = reactive({ data:null as Workspace|null, loading:false, error:'',authRequired:false,authMessage:'' })
let generation=0
let flight:{generation:number;promise:Promise<Workspace|null>}|null=null
export const personal = computed(()=>['patient','representative'].includes(work.data?.scope.role_code))
export const resources = computed(()=>work.data?.resources||{})
export const roleNames:Record<string,string>={patient:'患者',representative:'授权代办人',reception:'前台接待',dentist:'牙医',manager:'诊所主管',business:'总部业务',finance:'总部财务',director:'总部负责人'}
export const sections=[
 {name:'预约与诊疗',codes:['UC02','UC03','UC04','UC05','UC13','UC06','UC14']},
 {name:'患者与资源',codes:['UC01','UC09','UC15','UC07','UC08','UC10']},
 {name:'经营与管理',codes:['UC11','UC12','UC16','UC17']}
]
export const caseIcons:Record<string,string>={UC01:'person',UC02:'calendar',UC03:'refreshempty',UC04:'staff',UC05:'compose',UC06:'wallet',UC07:'location',UC08:'medal',UC09:'calendar-filled',UC10:'list',UC11:'wallet',UC12:'bars',UC13:'flag',UC14:'list',UC15:'gear',UC16:'locked',UC17:'checkbox'}
export const caseHints:Record<string,string>={UC01:'身份、联系人与逐项过敏',UC02:'完整时段与明确接诊安排',UC03:'原约保留，变更可追溯',UC04:'到店、候诊与实际接诊',UC05:'实际实施、同意与签署',UC06:'签署来源与有效结算版本',UC07:'门店资料及任职责任',UC08:'专业资格与有效期间',UC09:'有效出诊、跨店转场与替班',UC10:'项目、计量与价格标准',UC11:'费用来源、分摊与独立复核',UC12:'季度来源与集团经营',UC13:'阶段条件、实施与待约接续',UC14:'本人安排与已生效费用',UC15:'营业日历与可用诊疗位',UC16:'独立账号及岗位范围',UC17:'实际主体与业务版本'}
export function caseLabel(code:string,fallback:string){const names:Record<string,string>=personal.value?{UC01:'我的资料',UC02:'预约就诊',UC03:'我的预约',UC04:'到店报到',UC14:'治疗与费用'}:{UC01:'患者资料',UC03:'预约管理',UC04:'到店与接诊',UC05:'诊疗记录',UC06:'费用结算',UC07:'门店管理',UC08:'职员与资格',UC09:'医生与排班',UC10:'治疗项目与标准',UC11:'费用与复核',UC12:'季度经营分析',UC13:'阶段治疗方案',UC15:'营业与诊疗资源',UC16:'账号与权限',UC17:'操作记录'};return names[code]||fallback}
export function canUse(code:string){return !!work.data?.menu.some(item=>item.code===code)}
export function resetWorkspace(){generation++;flight=null;work.data=null;work.error='';work.loading=false;work.authRequired=false;work.authMessage=''}
export async function loadWorkspace(force=false):Promise<Workspace|null>{
 if(!session.token){resetWorkspace();return null}
 if(work.data&&!force)return work.data
 if(flight?.generation===generation)return flight.promise
 const epoch=generation;work.loading=true;work.error=''
 const promise=request('/api/workspace').then((data:Workspace)=>{if(epoch===generation){const belongs=clientSurface==='patient'?['patient','representative'].includes(data.scope.role_code):!['patient','representative'].includes(data.scope.role_code);if(!belongs||(data.application_surface&&data.application_surface!==clientSurface)){clearToken();throw Error(clientSurface==='patient'?'此入口仅供患者及授权代办人使用，请使用诊所管理系统登录工作账号':'此入口仅供诊所工作人员使用，患者请使用微信小程序')}data.teaching=inTeachingSession();work.data=data;session.scope=data.scope}return epoch===generation?data:null}).catch((error:Error)=>{if(epoch===generation)work.error=error.message;throw error}).finally(()=>{if(epoch===generation){work.loading=false;flight=null}})
 flight={generation:epoch,promise};return promise
}
export async function signIn(name:string,password:string,teaching=false){resetWorkspace();session.token='';session.scope=null;clearToken();await login(name,password,teaching);return loadWorkspace(true)}
export function signOut(){session.token='';session.scope=null;clearToken();resetWorkspace();uni.reLaunch({url:'/pages/index/index'})}
export async function selectScopeById(id:number,url='/pages/index/index'){
 const scope=work.data?.scopes.find(item=>item.id===id)
 if(!scope)return
 if(work.data?.scope.id===id){
  if(url!=='/pages/index/index')navigate(url)
  return
 }
 await switchScope(scope.id)
 resetWorkspace()
 await loadWorkspace(true)
 uni.reLaunch({url})
}
export async function selectScope(index:number){
 const scope=work.data?.scopes[index]
 if(scope)await selectScopeById(scope.id)
}
export async function requireWorkspace(code?:string){if(work.authRequired)return null;try{const data=await loadWorkspace(true);if(data&&code&&!data.menu.some(item=>item.code===code)){uni.showToast({title:'当前身份没有该事项权限',icon:'none'});goHome();return null}if(!data&&!work.authRequired)uni.reLaunch({url:'/pages/index/index'});return data}catch(error){if(!session.token&&!work.authRequired)uni.reLaunch({url:'/pages/index/index'});return null}}
function routeKey(route:string,options:Record<string,any>={}){return route.replace(/^\//,'')+'?'+Object.entries(options).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(String(v))).join('&')}
export function navigate(url:string){const [route,query='']=url.split('?');const options=Object.fromEntries(query.split('&').filter(Boolean).map(pair=>{const [key,...value]=pair.split('=');return[decodeURIComponent(key),decodeURIComponent(value.join('='))]}));const stack=getCurrentPages();const found=stack.findIndex((page:any)=>routeKey(page.route,page.options||{})===routeKey(route,options));if(found===stack.length-1&&found>=0)return;if(found>=0){uni.navigateBack({delta:stack.length-1-found});return}if(stack.length>=8)uni.redirectTo({url});else uni.navigateTo({url})}
export function goHome(){const stack=getCurrentPages();const found=stack.findIndex((page:any)=>page.route==='pages/index/index');if(found===stack.length-1&&found>=0)return;if(found>=0)uni.navigateBack({delta:stack.length-1-found});else uni.reLaunch({url:'/pages/index/index'})}
export async function restoreSession(password:string){const expected=work.data;if(!expected)throw Error('请返回登录页核实账号');const result=await request('/api/auth/login',{login_name:expected.account.login_name,password},undefined,expected.teaching);if(result.account.id!==expected.account.id||!result.scopes.some((s:Row)=>s.id===expected.scope.id))throw Error('原岗位授权已变化，请返回登录页选择有效身份');saveToken(result.token);try{if(result.scope.id!==expected.scope.id)await switchScope(expected.scope.id);await loadWorkspace(true);work.authRequired=false;work.authMessage=''}catch(error){session.token='';clearToken();throw error}}
export function caseUrl(code:string,params:Record<string,string|number>={}){
 const paths:Record<string,string>={UC02:'/pages/appointments/book',UC03:'/pages/appointments/index',UC09:'/pages/schedule/index',UC12:'/pages/analytics/index',UC17:'/pages/audit/index',...(personal.value?{UC14:'/pages/journey/index'}:{})}
 const path=paths[code]||'/pages/operations/index'
 const query=Object.entries({case:code,...params}).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(String(v))).join('&')
 return path+'?'+query
}
export function goCase(code:string,params:Record<string,string|number>={}){
 if(!canUse(code)){uni.showToast({title:'当前岗位未获授权',icon:'none'});return}
 navigate(caseUrl(code,params))
}
function shanghai(value?:string|Date){return new Date((value?new Date(value):new Date()).getTime()+8*3600000)}
export function localDay(value?:string|Date){const date=shanghai(value);return [date.getUTCFullYear(),String(date.getUTCMonth()+1).padStart(2,'0'),String(date.getUTCDate()).padStart(2,'0')].join('-')}
export function dayLabel(value?:string){if(!value)return '日期待确认';const d=shanghai(value);return `${d.getUTCMonth()+1}月${d.getUTCDate()}日 周${'日一二三四五六'[d.getUTCDay()]}`}
export function clock(value?:string){if(!value)return '—';const d=shanghai(value);return String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0')}
export function queryString(values:Record<string,any>){return Object.entries(values).filter(([,value])=>value!==undefined&&value!==null).map(([key,value])=>encodeURIComponent(key)+'='+encodeURIComponent(String(value))).join('&')}
export function money(value:any){return Number(value||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}
export function wechatTitleBounds(info:{windowWidth:number;statusBarHeight?:number},capsule:{left:number;right:number;bottom:number}){
 const top=info.statusBarHeight||0
 const valid=capsule.left>info.windowWidth/2&&capsule.right>capsule.left&&capsule.right<=info.windowWidth+1&&capsule.bottom>top
 const right=valid?Math.max(info.windowWidth-capsule.left+8,16):104
 const height=valid?Math.max(top+48,capsule.bottom+8):top+48
 return {top,right,height}
}
export function clinicName(id:any){return resources.value.clinics?.find(row=>row.id===id)?.clinic_name||'承接门店待确认'}
export function doctorName(id:any){return resources.value.dentists?.find(row=>row.id===id)?.full_name||'负责牙医待确认'}

uni.$on('adc:authentication-lost',(message:string)=>{generation++;flight=null;work.loading=false;work.authRequired=true;work.authMessage=message;session.scope=null})
