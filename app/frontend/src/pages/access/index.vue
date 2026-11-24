<script setup lang="ts">
import {ref,reactive,computed} from 'vue'
import {onLoad,onUnload} from '@dcloudio/uni-app'
import AppIcon from '../../components/AppIcon.vue'
import AdcField from '../../components/AdcField.vue'
import {request,saveToken,clientSurface} from '../../api'
import {resetWorkspace,loadWorkspace,navigate,roleNames,localDay} from '../../workspace'
const isStaffPortal=clientSurface==='staff'
const mode=ref('wechat'),step=ref('start'),busy=ref(false),error=ref(''),accepted=ref(false),ticket=ref(''),resetTicket=ref(''),identities=ref<any[]>([]),message=ref('')
const form=reactive({account_kind:'patient',full_name:'',birth_date:'',phone:'',billing_address:'',email:'',sex_code:'unknown',emergency_name:'',emergency_phone:'',emergency_relationship:'',allergy_declaration:'unknown',allergy_substance_id:'',allergy_reaction:'',login_name:'',password:'',confirm:''})
const publicResources=ref<Record<string,any[]>>({allergy_substances:[]})
const profileFields=[{key:'emergency_name',label:'紧急联系人姓名',required:true},{key:'emergency_phone',label:'紧急联系人电话',required:true},{key:'emergency_relationship',label:'与患者关系',required:true},{key:'allergy_declaration',label:'过敏申报状态',type:'enum:unknown=尚未采集或不确定,denied=本人否认已知过敏,reported=本人申报已知过敏',required:true}]
const bindForm=reactive({login_name:'',password:''}),target=ref<any>(null)
let isWechat=false,top=0
// #ifdef MP-WEIXIN
isWechat=true;top=uni.getSystemInfoSync().statusBarHeight||0
// #endif
const heading=computed(()=>step.value==='reset'?'重设账号密码':step.value==='bind'?'绑定已有账号':step.value==='identities'?'选择本次使用的身份':step.value==='register'?'建立你的服务账号':mode.value==='recover'?'找回账号密码':'微信登录')
const roleChoices=[{id:'patient',title:'患者',text:'登记本人资料，预约与查询本人服务。'},{id:'representative',title:'监护人或授权代办人',text:'先建立账号，由门店核实患者及授权事项。'}]
onLoad(async(q:any)=>{mode.value=q?.mode||'wechat';if(mode.value==='register')step.value='register';try{const result=await request('/api/auth/options');publicResources.value={allergy_substances:result.allergy_substances||[]}}catch(e:any){error.value=e.message}})
onUnload(()=>{ticket.value='';resetTicket.value='';form.password='';form.confirm='';bindForm.password=''})
async function run(action:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await action()}catch(e:any){error.value=e.message||'办理未完成，请稍后重试'}finally{busy.value=false}}
function requireConsent(){if(!accepted.value)throw Error('请先阅读并同意隐私说明')}
function receive(result:any){ticket.value=result.identity_ticket||ticket.value;identities.value=result.identities||[];step.value=result.state==='register_or_bind'?'register':'identities'}
async function startWechat(){await run(async()=>{requireConsent();if(!isWechat)throw Error('请在微信小程序中完成微信验证，或联系门店核实找回账号');const login=await new Promise<any>((resolve,reject)=>uni.login({provider:'weixin',success:resolve,fail:()=>reject(Error('微信验证未完成，请重新点击微信登录'))}));if(!login.code)throw Error('未取得微信验证凭证，请重试');receive(await request('/api/auth/wechat',{code:login.code,privacy_accepted:true}))})}
async function choose(account:any,scope?:any){await run(async()=>{target.value=account;if(mode.value==='recover'){const result=await request('/api/auth/recovery',{identity_ticket:ticket.value,account_id:account.id});resetTicket.value=result.reset_ticket;form.password='';form.confirm='';step.value='reset';return}if(!scope)throw Error('该账号尚未获授权，请联系门店或总部核实');const result=await request('/api/auth/wechat/select',{identity_ticket:ticket.value,account_id:account.id,scope_id:scope.id});resetWorkspace();saveToken(result.token);await loadWorkspace(true);uni.reLaunch({url:'/pages/index/index'})})}
async function bind(){await run(async()=>{requireConsent();if(!ticket.value)throw Error('请先进行微信验证');const result=await request('/api/auth/wechat/bind',{identity_ticket:ticket.value,...bindForm});bindForm.password='';receive(result)})}
async function register(){await run(async()=>{requireConsent();if(form.account_kind==='employee'){if(ticket.value){step.value='bind';return}throw Error('工作人员由有权人员开通账号并授权，请用已有工作账号登录')}if(form.password!==form.confirm)throw Error('两次输入的密码不一致');const result=await request('/api/auth/register',{...form,identity_ticket:ticket.value||undefined,privacy_accepted:true});form.password='';form.confirm='';if(result.identity_ticket){receive(result);return}message.value=result.message;step.value='pending'})}
async function reset(){await run(async()=>{if(form.password!==form.confirm)throw Error('两次输入的密码不一致');const result=await request('/api/auth/reset-password',{reset_ticket:resetTicket.value,password:form.password});resetTicket.value='';ticket.value='';form.password='';form.confirm='';message.value=result.message;step.value='pending'})}
function back(){if(getCurrentPages().length>1)uni.navigateBack();else uni.reLaunch({url:'/pages/index/index'})}
function birthChanged(e:any){form.birth_date=e.detail.value}
function scopeLabel(scope:any){return scope.scope_kind==='group'?'集团授权范围':scope.scope_kind==='clinic'?(scope.clinic_name||'已授权门店'):scope.scope_kind==='self'?'本人资料与服务':(scope.authorized_patient_name?'患者 '+scope.authorized_patient_name+' 的有效授权事项':'指定患者的有效授权事项')}
</script>
<template>
 <view class="access-page"><view class="access-topbar" :style="{paddingTop:(top+10)+'px'}"><button aria-label="返回" @click="back"><AppIcon name="left"/></button><text>账号与身份</text></view>
 <view class="access-content"><template v-if="isStaffPortal"><text class="eyebrow">ADC 牙科诊所管理系统</text><text class="access-heading">工作人员账号协助</text><view class="access-explanation"><text>工作账号由总部业务人员准备，由有权负责人确认岗位与门店范围，不开放自助注册或微信绑定。</text><text>忘记密码或需要更换岗位，请联系有权的账号管理员核实。请勿发送原密码。</text><text>患者及监护人请使用微信小程序办理就诊事项。</text><text selectable>联系邮箱：2684077388@qq.com</text></view><button class="primary access-primary" @click="back">返回管理系统登录</button></template><template v-else><text class="eyebrow">ADC 诊所服务</text><text class="access-heading">{{heading}}</text><text class="access-intro">患者与代办分别建号。代办范围以门店核实的患者、事项及有效期为准。</text>
 <template v-if="step==='start'">
  <view class="access-explanation"><text>{{mode==='recover'?'已绑定微信的账号，可以验证后重设密码。':'验证微信后，选择已有身份，或建立新的患者服务账号。'}}</text><text>不读取微信头像、昵称或通讯录。</text></view>
  <button v-if="isWechat" class="primary access-primary" :disabled="busy" @click="startWechat">{{busy?'正在验证…':mode==='recover'?'微信验证找回':'微信登录'}}</button>
  <view v-if="mode==='recover'" class="recovery-help"><text>尚未绑定微信？</text><text>请联系门店接待；工作人员账号由有权的总部人员核实重置。请勿发送原密码或证件照片。</text><text selectable>联系邮箱：2684077388@qq.com</text></view>
  <button v-else class="plain-link" @click="step='register'">注册账号</button>
 </template>
 <template v-else-if="step==='identities'">
  <view v-for="account in identities" :key="account.id" class="identity-group"><text class="identity-name">{{account.display_name}}</text><text class="identity-account">账号 {{account.login_name}}</text>
   <button v-if="mode==='recover'" class="identity-row" @click="choose(account)"><text>验证此账号并重设密码</text><AppIcon name="right" :size="16"/></button>
   <template v-else><button v-for="scope in account.scopes" :key="scope.id" class="identity-row" :disabled="busy" @click="choose(account,scope)"><view><text>{{scope.role_name||roleNames[scope.role_code]}}</text><text class="identity-scope">{{scopeLabel(scope)}}</text></view><AppIcon name="right" :size="16"/></button><text v-if="!account.scopes?.length" class="pending-note">账号已建立，等待门店核实患者事项或岗位授权。</text></template>
  </view>
  <button class="plain-link" @click="step='bind'">绑定另一个已有账号</button><button class="plain-link" @click="step='register'">建立患者或代办账号</button>
 </template>
 <template v-else-if="step==='register'">
  <view class="role-list"><button v-for="item in roleChoices" :key="item.id" class="role-choice" :class="{selected:form.account_kind===item.id}" @click="form.account_kind=item.id"><view class="choice-mark"/><view><text class="role-title">{{item.title}}</text><text class="role-description">{{item.text}}</text></view></button></view>
  <template>
   <view class="field"><text class="label">{{form.account_kind==='patient'?'本人姓名':'代办人姓名'}}</text><input class="input" v-model="form.full_name" maxlength="100" placeholder="请填写本人姓名"/></view>
   <template v-if="form.account_kind==='patient'">
    <view class="field"><text class="label">出生日期</text><picker mode="date" :value="form.birth_date||'2000-01-01'" start="1900-01-01" :end="localDay()" @change="birthChanged"><view class="input picker-value">{{form.birth_date||'请选择出生日期'}}</view></picker></view>
    <view class="field"><text class="label">联系电话</text><input class="input" v-model="form.phone" maxlength="40" placeholder="用于服务联系，仍需按实际情况核实"/></view>
    <view class="field"><text class="label">通讯地址</text><input class="input" v-model="form.billing_address" maxlength="160" placeholder="暂不提供时请明确填写“暂不提供”"/></view>
    <AdcField v-for="field in profileFields" :key="field.key" :field="field" v-model="form[field.key as keyof typeof form]" :resources="publicResources"/>
    <template v-if="form.allergy_declaration==='reported'"><AdcField :field="{key:'allergy_substance_id',label:'过敏物质',type:'select:allergy_substances',required:true}" v-model="form.allergy_substance_id" :resources="publicResources"/><view class="field"><text class="label">过敏反应</text><textarea class="input" v-model="form.allergy_reaction" aria-label="过敏反应" placeholder="不清楚时请明确填写“不清楚”；更多过敏项请在建立账号后逐项补充"/></view><text class="field-help">按本人申报保存，尚待牙医核实。紧急联系人不自动取得代办或临床同意权限。</text></template>
    <text class="field-help">登记内容将在服务过程中核对。同名或共用电话不会自动接管已有档案；未满14周岁请由监护人联系门店核实。</text>
   </template>
   <view class="field"><text class="label">登录账号{{ticket?'（选填）':''}}</text><input class="input" v-model="form.login_name" maxlength="80" placeholder="字母、数字、点、下划线、@或短横线"/></view>
   <view class="field"><text class="label">密码{{ticket?'（选填）':''}}</text><input class="input" v-model="form.password" password maxlength="128" placeholder="12至128个字符"/></view>
   <view class="field"><text class="label">确认密码</text><input class="input" v-model="form.confirm" password maxlength="128" placeholder="再次输入密码"/></view>
   <text v-if="ticket" class="field-help">微信已验证。不设置密码时使用微信登录，可在“忘记密码”验证微信后设置账号密码。</text>
   <button class="primary access-primary" :disabled="busy" @click="register">{{busy?'正在建立…':form.account_kind==='patient'?'建立本人账号':'建立待授权代办账号'}}</button>
   <button v-if="isWechat&&!ticket" class="plain-link" :disabled="busy" @click="startWechat">使用微信注册或绑定已有账号</button>
  </template>
 </template>
 <template v-else-if="step==='bind'"><text class="field-help">仅绑定已有患者或授权代办账号，不提供工作人员身份。</text><view class="field"><text class="label">原登录账号</text><input class="input" v-model="bindForm.login_name" placeholder="已有患者或代办账号"/></view><view class="field"><text class="label">原账号密码</text><input class="input" v-model="bindForm.password" password placeholder="验证原账号后才会绑定微信"/></view><button class="primary access-primary" :disabled="busy" @click="bind">{{busy?'正在核实…':'核实并绑定微信'}}</button></template>
 <template v-else-if="step==='reset'"><text class="field-help">正在重设 {{target?.login_name}} 的密码；完成后原登录会话失效。</text><view class="field"><text class="label">新密码</text><input class="input" v-model="form.password" password maxlength="128" placeholder="12至128个字符"/></view><view class="field"><text class="label">确认新密码</text><input class="input" v-model="form.confirm" password maxlength="128" placeholder="再次输入新密码"/></view><button class="primary access-primary" :disabled="busy" @click="reset">{{busy?'正在重设…':'重设密码'}}</button></template>
 <template v-else-if="step==='pending'"><view class="access-explanation"><AppIcon name="checkbox" :size="28"/><text>{{message}}</text></view><button class="primary access-primary" @click="back">返回登录</button></template>
 <view v-if="error" class="error"><text selectable>{{error}}</text></view>
 <button v-if="isWechat&&['identities','bind','reset'].includes(step)" class="plain-link" :disabled="busy" @click="startWechat">重新验证微信</button>
 <view v-if="!['pending','identities','reset'].includes(step)" class="consent-row"><button class="consent-control" :aria-label="accepted?'取消同意隐私说明':'同意隐私说明'" @click="accepted=!accepted"><view class="consent-box" :class="{checked:accepted}">{{accepted?'✓':''}}</view><text>我已阅读并同意</text></button><button class="plain-link" @click="navigate('/pages/privacy/index')">隐私说明</button></view>
 <text class="access-footnote">课程项目，请使用合成资料。此入口仅提供患者及有效授权代办服务。</text>
 </template></view></view>
</template>
<style scoped>
.access-page{min-height:100vh;background:#f2f5f8;padding-bottom:calc(30px + env(safe-area-inset-bottom))}.access-topbar{display:flex;align-items:center;gap:10px;padding:14px 22px;background:#fff;border-bottom:1px solid #e3e8ef;font-size:17px;font-weight:600;min-height:60px}.access-topbar button{background:transparent;border:0;padding:10px;min-height:44px}.access-content{max-width:540px;margin:38px auto;background:#fff;border:1px solid #e3e8ef;border-radius:12px;padding:34px}.eyebrow{color:#3278cf;font-size:12px;display:block;margin-bottom:12px}.access-heading{font-size:25px;line-height:1.5;font-weight:600;display:block}.access-intro{display:block;font-size:13px;color:#758296;line-height:1.9;margin-top:12px;margin-bottom:26px}.access-explanation{display:flex;flex-direction:column;gap:12px;line-height:1.9;font-size:14px;padding:20px 0}.access-primary{width:100%;margin-top:22px;min-height:48px}.plain-link{border:0;background:transparent;color:#3278cf;font-size:13px;min-height:36px;padding:6px 0}.recovery-help{margin-top:30px;border-top:1px solid #e3e8ef;padding-top:20px;display:flex;flex-direction:column;gap:10px;font-size:13px;line-height:1.9;color:#758296}.recovery-help>text:first-child{color:#253347;font-weight:500}.identity-group{border-top:1px solid #e3e8ef;padding:20px 0}.identity-name{font-size:17px;font-weight:600;display:block}.identity-account{font-size:12px;color:#758296;display:block;margin-top:5px}.identity-row{display:flex;align-items:center;justify-content:space-between;width:100%;background:transparent;border:0;border-bottom:1px solid #e3e8ef;text-align:left;gap:15px;padding:17px 0;font-size:15px}.identity-scope{display:block;font-size:12px;color:#758296;margin-top:5px;font-weight:400}.pending-note,.field-help{display:block;font-size:12px;color:#758296;line-height:1.9;margin:12px 0}.role-list{margin-bottom:22px}.role-choice{display:flex;align-items:flex-start;gap:13px;border:0;border-bottom:1px solid #e3e8ef;background:transparent;border-radius:0;width:100%;padding:17px 0;text-align:left}.choice-mark{width:18px;height:18px;border-radius:50%;border:1px solid #758296;flex-shrink:0;margin-top:3px}.selected .choice-mark{border:5px solid #3278cf}.role-title{display:block;font-size:15px;font-weight:500}.role-description{display:block;font-size:12px;line-height:1.8;color:#758296;font-weight:400;margin-top:5px}.picker-value{line-height:1.8;min-height:45px;display:flex;align-items:center}.consent-row{display:flex;align-items:center;gap:5px;margin-top:24px;font-size:12px;flex-wrap:wrap}.consent-control{background:transparent;border:0;padding:0;display:flex;align-items:center;gap:9px;min-height:44px;font-size:12px;color:#758296}.consent-box{width:19px;height:19px;border:1px solid #758296;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:13px}.consent-box.checked{color:#fff;background:#3278cf;border-color:#3278cf}.access-footnote{font-size:11px;color:#758296;line-height:1.9;display:block;border-top:1px solid #e3e8ef;margin-top:24px;padding-top:18px}@media(max-width:680px){.access-content{margin:20px 18px;padding:24px 20px}.access-topbar{padding-left:8px}.access-heading{font-size:23px}.access-intro{font-size:12px}.access-explanation{font-size:13px}.role-description{font-size:12px}.consent-row{font-size:11px}.access-primary{margin-top:18px}}
</style>
