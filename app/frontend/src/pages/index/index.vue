<script setup lang="ts">
import { computed, ref } from 'vue'
import teaching from '../../teaching.json'
import { onShow } from '@dcloudio/uni-app'
import WorkspaceShell from '../../components/WorkspaceShell.vue'
import AppIcon from '../../components/AppIcon.vue'
import PatientHome from './PatientHome.vue'
// #ifndef MP-WEIXIN
import StaffHome from './StaffHome.vue'
// #endif
import { session,request,clientVersion,clientSurface } from '../../api'
import {work,personal,loadWorkspace,signIn,navigate,roleNames,wechatTitleBounds} from '../../workspace'
const isStaffPortal=clientSurface==='staff'
const ownAccount = 'custom'
const staffRoles = ['reception','dentist','manager','business','finance','director']
const patientRoles = ['patient','representative']
const identities = (isStaffPortal ? staffRoles : patientRoles).map(value => ({
 value, label: value === 'patient' ? '患者本人' : roleNames[value]
})).concat({ value: ownAccount, label: '使用自己的账号' })
const nativeIdentities = [{ value: '', label: '请选择登录身份' }, ...identities]
const identity = ref('')
const manualName = ref('')
const password = ref('')
const loginName = computed(() => identity.value === ownAccount ? manualName.value.trim() : identity.value)
const selectedIndex = computed(() => identities.findIndex(option => option.value === identity.value))
const selectedLabel = computed(() => identities[selectedIndex.value]?.label || '请选择登录身份')
const busy = ref(false), error = ref(''), passwordMode = ref(true)
const showPassword = ref(false)
function selectIdentity(value: string) {
 if (busy.value || value === identity.value || !identities.some(option => option.value === value)) return
 identity.value = value
 manualName.value = ''
 password.value = ''
 showPassword.value = false
 error.value = ''
}
function selectWebIdentity(event: Event) {
 selectIdentity((event.target as HTMLSelectElement).value)
}
function selectNativeIdentity(event: {detail: {value: string | number}}) {
 const option = nativeIdentities[Number(event.detail.value)]
 if (option) selectIdentity(option.value)
}
const connectionStatus=ref(''),checkingConnection=ref(false)
async function checkConnection(){checkingConnection.value=true;connectionStatus.value='正在检查微信与服务的连接…';try{const result=await request('/healthz');connectionStatus.value=result.status==='ok'?'服务连接正常，请重新登录。':'服务尚未就绪，请稍后重试。'}catch(e:any){connectionStatus.value=e.message}finally{checkingConnection.value=false}}
let loginStyle:Record<string,string>={}
let loginHeaderStyle:Record<string,string>={}
let patientTitle='ADC 诊所服务'
// #ifdef MP-WEIXIN
passwordMode.value=false
const system=uni.getSystemInfoSync()
const capsule=uni.getMenuButtonBoundingClientRect()
const titleBounds=wechatTitleBounds(system,capsule)
loginStyle={paddingTop:(titleBounds.height+16)+'px'}
loginHeaderStyle={height:titleBounds.height+'px',paddingTop:titleBounds.top+'px',paddingRight:titleBounds.right+'px'}
patientTitle='牙科诊所'
// #endif
onShow(()=>{if(session.token)loadWorkspace(true).catch(e=>error.value=e.message)})
async function enter() {
 if (busy.value || work.loading || !loginName.value || !password.value) return
 busy.value=true
 error.value=''
 try {
  await signIn(loginName.value,password.value,identity.value !== ownAccount)
  password.value=''
  showPassword.value=false
 } catch(e:any) {
  error.value=e.message
 } finally {
  busy.value=false
 }
}
</script>
<template>
 <view v-if="!session.token||!work.data" class="login-layout" :style="loginStyle">
  <!-- #ifdef MP-WEIXIN -->
  <view class="login-native-brand" :style="loginHeaderStyle">
   <text class="login-native-mark">ADC</text>
   <text class="login-native-title">牙科诊所</text>
  </view>
  <!-- #endif -->
  <view class="login-story"><view class="login-brand"><text class="brand-monogram">ADC</text><view><text class="login-brand-title">牙科诊所</text><text class="muted small">{{isStaffPortal?'连锁门店 · 员工工作入口':'预约就诊 · 患者服务'}}</text></view></view><text class="login-heading">{{isStaffPortal?'ADC牙科诊所管理系统':'欢迎来到ADC患者服务'}}</text><text class="login-description">{{isStaffPortal?'从预约接诊、临床签署到门店资源和季度经营，按岗位职责衔接每一步。':'预约就诊、接续治疗与费用查询，在这里清楚地安排。'}}</text><image src="/static/images/clinic-scene.jpg" mode="aspectFill" class="login-scene"/><view class="login-principles"><view><AppIcon name="calendar"/><text>营业、资质与诊疗资源共同核验</text></view><view><AppIcon name="flag"/><text>治疗有阶段，接续有依据</text></view><view><AppIcon name="locked"/><text>{{isStaffPortal?'按岗位、门店与集团范围访问':'仅查看本人或有效授权患者的事项'}}</text></view></view></view>
  <view class="login-card"><text class="login-card-title">{{isStaffPortal?'工作人员登录':'患者登录'}}</text><text class="login-card-intro">{{isStaffPortal?'选择岗位使用教学账号，或选择自己的工作账号':'选择身份使用教学账号，或选择自己的患者服务账号'}}</text>
<!-- #ifdef MP-WEIXIN -->
<button class="primary wechat-entry" @click="navigate('/pages/access/index?mode=wechat')">微信登录</button><button class="password-toggle" @click="passwordMode=!passwordMode">{{passwordMode?'收起账号密码':'账号密码登录'}}</button>
<!-- #endif -->
<template v-if="passwordMode">
 <view class="field">
  <text class="label">登录身份</text>
  <!-- #ifdef H5 -->
  <select class="input identity-select" aria-label="登录身份" :value="identity" :disabled="busy" @change="selectWebIdentity">
   <option disabled value="">请选择登录身份</option>
   <option v-for="option in identities" :key="option.value" :value="option.value">{{option.label}}</option>
  </select>
  <!-- #endif -->
  <!-- #ifdef MP-WEIXIN -->
  <picker mode="selector" :range="nativeIdentities" range-key="label" :value="selectedIndex + 1" :disabled="busy" @change="selectNativeIdentity">
   <view class="input identity-native"><text>{{selectedLabel}}</text><text aria-hidden="true">⌄</text></view>
  </picker>
  <!-- #endif -->
  <text v-if="identity && identity !== ownAccount" class="identity-account">教学账号 · {{loginName}}</text>
 </view>
 <view v-if="identity === ownAccount" class="field">
  <text class="label">登录账号</text><input class="input" aria-label="登录账号" placeholder="请输入自己的账号" v-model="manualName" :disabled="busy"/>
 </view>
 <view class="field"><text class="label">密码</text><view class="password-input-row"><input class="input password-entry" aria-label="密码" placeholder="请输入所选账号的密码" :password="!showPassword" v-model="password" :disabled="busy" @confirm="enter"/><button class="password-visibility" :aria-label="showPassword?'隐藏密码':'显示密码'" :aria-pressed="showPassword" :disabled="busy" @click="showPassword=!showPassword">{{showPassword?'隐藏密码':'显示密码'}}</button></view></view>
 <text v-if="identity !== ownAccount" selectable class="teaching-hint">教学密码：{{teaching.password}}（区分大小写）<text class="teaching-detail">教学身份共用模拟资料，请使用虚构信息。</text></text>
 <view v-if="error" class="error"><text selectable>{{error}}</text></view>
 <button class="primary login-button" :disabled="busy || work.loading || !loginName || !password" @click="enter">{{busy?'正在登录…':'登录'}}</button>
</template><view class="login-connection"><text>版本 {{clientVersion}}</text><button :disabled="checkingConnection" @click="checkConnection">{{checkingConnection?'检查中…':'检查连接'}}</button></view><text v-if="connectionStatus" selectable class="connection-result">{{connectionStatus}}</text><view class="account-links"><button v-if="!isStaffPortal" @click="navigate('/pages/access/index?mode=register')">注册患者账号</button><button @click="navigate('/pages/access/index?mode=recover')">忘记密码</button></view><text class="login-help">{{isStaffPortal?'本入口仅供前台、牙医及已授权管理人员使用。患者请使用微信小程序；工作账号由有权人员开通。':'本入口仅供患者及已授权代办人使用。医生、前台及管理人员请使用诊所管理系统。'}}</text><view class="login-privacy"><text>课程项目 · 请使用模拟资料</text><button @click="navigate('/pages/privacy/index')">隐私说明</button></view></view>
 </view>
 <WorkspaceShell v-else :title="personal?patientTitle:'工作台'" active="home">
  <PatientHome v-if="personal"/>
  <!-- #ifndef MP-WEIXIN -->
  <StaffHome v-else/>
  <!-- #endif -->
 </WorkspaceShell>
</template>
<style scoped>
/* #ifdef MP-WEIXIN */
.login-layout{position:relative}
.login-native-brand{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:8px;padding-left:16px;box-sizing:border-box;background:#fff;border-bottom:1px solid #e3e8ef}
.login-native-mark{display:flex;align-items:center;justify-content:center;flex:0 0 28px;height:28px;border-radius:7px;color:#fff;background:#3278cf;font-size:10px;font-weight:700}
.login-native-title{min-width:0;color:#253347;font-size:17px;font-weight:650;line-height:1.3}
.login-layout .login-brand{display:none}
/* #endif */
.login-connection{display:flex;align-items:center;justify-content:space-between;margin-top:12px;font-size:11px;color:#758296}
.login-connection button{background:transparent;border:0;color:#3278cf;font-size:12px;padding:4px 0;min-height:32px}
.connection-result{display:block;font-size:12px;line-height:1.7;margin-top:6px;overflow-wrap:anywhere}
.login-layout{max-width:1136px;min-height:100vh;margin:auto;padding:72px 36px;display:grid;grid-template-columns:minmax(0,1fr) 420px;align-items:center;gap:96px}
.login-brand{display:flex;align-items:center;gap:12px}
.brand-monogram{width:44px;height:44px;display:flex;align-items:center;justify-content:center;border-radius:11px;color:#fff;background:#3278cf;font-size:14px;font-weight:700}
.login-brand-title{display:block;font-size:20px;font-weight:600;margin-bottom:2px}
.login-heading{display:block;font-size:38px;line-height:1.5;font-weight:600;letter-spacing:1px;margin:62px 0 20px}
.login-description{display:block;font-size:16px;color:#758296;line-height:1.9;max-width:370px}
.login-principles{margin-top:44px;display:flex;flex-direction:column;gap:18px}
.login-principles>view{display:flex;align-items:center;gap:12px;font-size:14px}
.login-card{padding:36px;background:#fff;border:1px solid #e3e8ef;border-radius:16px;box-shadow:0 3px 12px rgba(37,51,71,.04)}
.login-card-title{display:block;font-size:24px;font-weight:600}
.login-card-intro{display:block;font-size:14px;color:#758296;margin:9px 0 30px}
.login-button{width:100%;margin-top:24px}
.login-help{display:block;color:#758296;font-size:12px;line-height:1.8;margin-top:20px}
.login-privacy{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #e3e8ef;padding-top:15px;margin-top:22px;font-size:11px;color:#758296}
.login-privacy button{border:0;background:transparent;min-height:30px;padding:4px 0;font-size:12px;color:#3278cf}
@media(max-width:1050px){.login-layout{gap:48px;padding:48px 30px;grid-template-columns:1fr 400px}
.login-heading{font-size:32px}}
@media(max-width:680px){.login-layout{display:flex;flex-direction:column;gap:26px;align-items:stretch;padding:36px 24px}
.login-heading{font-size:25px;margin:28px 0 0;line-height:1.55}
.login-description, .login-principles{display:none}
.login-brand-title{font-size:18px}
.login-card{padding:25px 22px;border-radius:13px}
.login-card-title{font-size:21px}
.login-card-intro{margin-bottom:24px;font-size:13px}
.login-privacy{font-size:10px}}
.login-heading{margin:32px 0 16px}
.login-scene{width:100%;height:218px;border-radius:9px;margin-top:25px;display:block}
.login-principles{margin-top:23px;gap:13px}
.login-principles>view{font-size:12px}
.login-layout{padding-top:48px;padding-bottom:48px}
.login-card{box-shadow:none}
@media(max-width:680px){.login-scene{height:125px;margin-top:20px;border-radius:8px}
.login-heading{display:none}
.login-layout{gap:22px;padding-top:30px}
.login-card{border:0;background:transparent;padding:6px 0}
.login-card-title{font-size:23px}
.login-card-intro{margin:8px 0 24px}
.login-help{font-size:11px}
.login-principles{display:none}}
.wechat-entry{width:100%;margin:8px 0 14px;min-height:48px}
.account-links{display:flex;justify-content:space-between;margin-top:15px}
.account-links button{background:transparent;border:0;color:#3278cf;font-size:12px;padding:5px 0;min-height:36px}
.password-toggle{display:block;width:100%;background:transparent;border:0;color:#3278cf;font-size:13px;min-height:38px;margin:0 0 16px;padding:4px}
.wechat-entry{margin-top:4px}

.teaching-hint{display:block;margin-top:6px;color:#536b82;font-size:12px;line-height:1.6}.teaching-detail{display:block}
.identity-select{display:block;width:100%;font:inherit;cursor:pointer}
.identity-select:focus-visible{outline:2px solid #3278cf;outline-offset:2px}
.identity-native{display:flex;align-items:center;justify-content:space-between}
.identity-account{display:block;margin-top:6px;color:#536b82;font-size:12px}
.password-input-row{display:flex;align-items:stretch;min-width:0;gap:8px}
.password-entry{flex:1;min-width:0;width:0}
.password-visibility{flex:0 0 auto;min-width:76px;min-height:44px;padding:0 8px;border:1px solid #e3e8ef;border-radius:8px;background:#fff;color:#3278cf;font-size:13px;line-height:1.2}
.password-visibility:focus-visible{outline:2px solid #3278cf;outline-offset:2px}
</style>
