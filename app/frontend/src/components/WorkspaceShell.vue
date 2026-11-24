<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import SessionGate from './SessionGate.vue'
import { work,personal,sections,caseIcons,caseLabel,canUse,goCase,goHome,navigate,wechatTitleBounds,selectScopeById,caseUrl } from '../workspace'
const props=withDefaults(defineProps<{title:string;subtitle?:string;active?:string;back?:boolean;hideFooter?:boolean}>(),{subtitle:'',active:'home',back:false,hideFooter:false})
const groups=computed(()=>sections.map(group=>({...group,items:(work.data?.menu||[]).filter(item=>group.codes.includes(item.code))})).filter(group=>group.items.length))
const clinicsForRole=computed(()=>(work.data?.scopes||[]).filter(s=>s.scope_kind==='clinic'&&s.role_code===work.data?.scope.role_code))
const displayedScope=computed(()=>work.data?.scope.scope_kind==='group'
 ?'集团 · '+(work.data.resources.clinics?.length||0)+' 家门店'
 :work.data?.scope.clinic_name||work.data?.scope.role_name||'')
let environment=''
 // #ifdef H5
environment=/^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname)?'本机数据':'云端数据'
 // #endif
async function chooseClinic(event:{detail:{value:string|number}}){
 const selected=clinicsForRole.value[Number(event.detail.value)]
 if(selected)await activateClinic(selected.id)
}
async function activateClinic(id:number){
 const selected=clinicsForRole.value.find(item=>item.id===id)
 if(!selected||selected.id===work.data?.scope.id)return
 const active=props.active
 const target=['UC03','UC09','UC12'].includes(active)&&canUse(active)?caseUrl(active):'/pages/index/index'
 try{await selectScopeById(selected.id,target)}catch(error:any){uni.showToast({title:error.message,icon:'none'})}
}
const mainCase=computed(()=>({patient:'UC02',representative:'UC02',reception:'UC04',dentist:'UC04',manager:'UC09',business:'UC07',finance:'UC11',director:'UC12'} as Record<string,string>)[work.data?.scope.role_code as string]||'UC14')
const mainLabel=computed(()=>({patient:'预约',representative:'代办预约',reception:'到店',dentist:'接诊',manager:'排班',business:'门店',finance:'费用',director:'经营'} as Record<string,string>)[work.data?.scope.role_code as string]||'业务')
let nativeStyle:Record<string,string>={}
let hasWeChatCapsule=false
// #ifdef MP-WEIXIN
const info=uni.getSystemInfoSync(),capsule=uni.getMenuButtonBoundingClientRect()
const titleBounds=wechatTitleBounds(info,capsule)
hasWeChatCapsule=true
nativeStyle={paddingTop:titleBounds.top+'px',paddingRight:titleBounds.right+'px',minHeight:titleBounds.height+'px'}
// #endif
function goBack(){if(getCurrentPages().length>1)uni.navigateBack();else goHome()}
function appointments(){goCase('UC03')}
function myAccount(){navigate('/pages/me/index')}
function services(){navigate('/pages/services/index')}
</script>
<template>
 <view class="workspace-shell" :class="{'without-footer':hideFooter}">
  <view class="workspace-sidebar">
   <button class="brand-button" @click="goHome"><text class="brand-monogram">ADC</text><view><text class="brand-name">{{personal?'患者服务':'诊所管理系统'}}</text><text class="brand-description">{{personal?'我的就诊安排':'连锁协作 · 岗位工作台'}}</text></view></button>
   <!-- #ifdef H5 -->
   <view v-if="!personal" class="workspace-scope">
    <text class="scope-eyebrow">{{work.data?.teaching?'教学数据':environment}} · {{work.data?.scope.role_name}}</text>
    <select v-if="clinicsForRole.length>1" class="scope-control" aria-label="切换工作门店" :value="work.data?.scope.id" @change="activateClinic(Number(($event.target as HTMLSelectElement).value))">
     <option v-for="option in clinicsForRole" :key="option.id" :value="option.id">{{option.clinic_name}}</option>
    </select>
    <view v-else class="scope-choice"><AppIcon name="location" :size="18"/><text>{{displayedScope}}</text></view>
   </view>
   <!-- #endif -->
   <button class="side-item" :class="{selected:active==='home'}" @click="goHome"><AppIcon name="home" :color="active==='home'?'#3278cf':'#758296'"/><text>{{personal?'首页':'工作台首页'}}</text></button>
   <view v-for="group in groups" :key="group.name" class="side-group"><text class="side-group-title">{{group.name}}</text><button v-for="item in group.items" :key="item.code" class="side-item" :class="{selected:active===item.code}" @click="goCase(item.code)"><AppIcon :name="caseIcons[item.code]" :size="20" :color="active===item.code?'#3278cf':'#758296'"/><text>{{caseLabel(item.code,item.name)}}</text></button></view>
   <button class="sidebar-account" @click="myAccount"><view class="person-glyph"><AppIcon name="person" :size="23"/></view><view><text class="account-name">{{work.data?.account.display_name}}</text><text class="account-role">{{work.data?.scope.role_name}}</text></view><AppIcon name="right" :size="15" color="#758296"/></button>
  </view>
  <view class="workspace-main">
   <view class="workspace-topbar" :class="{'wechat-topbar':hasWeChatCapsule}" :style="nativeStyle">
    <view class="topbar-leading"><button v-if="props.back" class="icon-button" aria-label="返回上一页" @click="goBack"><AppIcon name="left" color="#253347"/></button><text v-else class="compact-mark">ADC</text><text class="topbar-title">{{title}}</text></view><button class="mobile-service-entry" aria-label="打开服务导航" @click="services"><AppIcon name="list" :size="20"/><text>导航</text></button>
    <picker v-if="!personal&&clinicsForRole.length>1" class="mobile-scope-picker" :range="clinicsForRole" range-key="clinic_name" @change="chooseClinic"><button class="mobile-scope-button">{{displayedScope}} <AppIcon name="down" :size="13"/></button></picker>
    <view class="desktop-topbar-meta"><text>{{personal?'患者服务':'牙科诊所管理系统'}}</text><text class="topbar-separator">/</text><text>{{personal?work.data?.scope.role_name:displayedScope}}</text><button class="topbar-account" @click="myAccount"><AppIcon name="person" :size="18"/><text>{{work.data?.account.display_name}}</text></button></view>
   </view>
   <view class="workspace-body" :style="work.authRequired?{visibility:'hidden'}:{}"><view v-if="subtitle" class="page-introduction"><text>{{subtitle}}</text><slot name="actions"/></view><view v-if="work.error" class="error">{{work.error}}</view><slot/></view>
  </view>
  <view v-if="!hideFooter" class="mobile-navigation">
   <button :class="{active:active==='home'}" @click="goHome"><AppIcon name="home" :color="active==='home'?'#3278cf':'#758296'"/><text>首页</text></button>
   <button v-if="personal&&canUse('UC03')" :class="{active:active==='UC03'||active==='UC02'}" @click="appointments"><AppIcon name="calendar" :color="active==='UC03'||active==='UC02'?'#3278cf':'#758296'"/><text>我的预约</text></button><button v-else-if="canUse(mainCase)" :class="{active:active===mainCase}" @click="goCase(mainCase)"><AppIcon :name="caseIcons[mainCase]" :color="active===mainCase?'#3278cf':'#758296'"/><text>{{mainLabel}}</text></button>
   <button v-if="personal&&canUse('UC14')" :class="{active:active==='UC14'}" @click="goCase('UC14',{dataset:'phases'})"><AppIcon name="flag" :color="active==='UC14'?'#3278cf':'#758296'"/><text>就诊与费用</text></button>
   <button v-else @click="services"><AppIcon name="list" color="#758296"/><text>全部业务</text></button>
   <button :class="{active:active==='me'}" @click="myAccount"><AppIcon name="person" :color="active==='me'?'#3278cf':'#758296'"/><text>我的</text></button>
  </view>
  <SessionGate v-if="work.authRequired"/>
 </view>
</template>
<style scoped>
.workspace-shell{min-height:100vh}.workspace-sidebar{position:fixed;top:0;bottom:0;left:0;width:240px;background:#fff;border-right:1px solid #e3e8ef;display:flex;flex-direction:column;overflow-y:auto;padding:24px 16px}.brand-button{display:flex;align-items:center;gap:11px;border:0;padding:0 8px 30px;text-align:left;background:transparent}.brand-monogram{display:flex;width:40px;height:40px;align-items:center;justify-content:center;background:#3278cf;border-radius:10px;color:#fff;font-size:13px;font-weight:700;flex-shrink:0}.brand-name{font-weight:600;font-size:19px;display:block}.brand-description{font-size:11px;color:#758296;display:block;margin-top:3px}.side-item{display:flex;align-items:center;gap:11px;text-align:left;border:0;border-radius:8px;font-size:14px;min-height:44px;padding:10px 12px;margin:2px 0;background:transparent}.side-item.selected{background:#edf5ff;color:#3278cf;font-weight:600}.side-group{margin-top:18px}.side-group-title{display:block;font-size:12px;color:#758296;padding:0 12px 7px}.sidebar-account{margin-top:auto;display:flex;gap:10px;align-items:center;text-align:left;border:0;border-top:1px solid #e3e8ef;border-radius:0;padding:22px 4px 0;background:transparent}.person-glyph{background:#edf5ff;border-radius:50%;width:38px;height:38px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.account-name{display:block;font-weight:600;font-size:14px}.account-role{display:block;color:#758296;font-size:12px;margin-top:2px}.sidebar-account>uni-icons{margin-left:auto}.workspace-main{margin-left:240px;min-width:0}.workspace-topbar{display:flex;align-items:center;justify-content:space-between;min-height:72px;background:#fff;border-bottom:1px solid #e3e8ef;padding:12px 32px;gap:20px}.topbar-leading{display:flex;align-items:center;gap:10px;min-width:0}.topbar-title{font-size:18px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.compact-mark{display:none}.desktop-topbar-meta{display:flex;align-items:center;gap:13px;font-size:13px;color:#758296}.topbar-separator{color:#e3e8ef}.topbar-account{display:flex;align-items:center;gap:8px;min-height:40px;border:0;padding:5px 0 5px 14px;font-size:13px;background:transparent;color:#253347}.workspace-body{max-width:1344px;padding:28px 32px 40px;margin:0 auto}.page-introduction{display:flex;align-items:center;justify-content:space-between;color:#758296;font-size:13px;margin-bottom:22px}.icon-button{display:flex;align-items:center;justify-content:center;min-width:44px;min-height:44px;padding:8px;border:0;background:transparent}.mobile-navigation,.mobile-service-entry{display:none}@media(max-width:1000px){.workspace-sidebar{width:216px;padding:20px 12px}.workspace-main{margin-left:216px}.workspace-body{padding:24px}.workspace-topbar{padding-left:24px;padding-right:24px}.desktop-topbar-meta>text{display:none}}@media(max-width:680px){.mobile-service-entry{display:flex;align-items:center;gap:5px;font-size:12px;background:transparent;border:0;padding:6px;min-width:60px}.workspace-sidebar{display:none}.workspace-main{margin:0}.workspace-topbar{padding:8px 16px;min-height:60px}.topbar-title{font-size:18px}.desktop-topbar-meta{display:none}.compact-mark{display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;background:#3278cf;color:#fff;font-size:10px;font-weight:700}.workspace-body{padding:22px 18px calc(92px + env(safe-area-inset-bottom))}.page-introduction{margin-bottom:16px;line-height:1.6}.mobile-navigation{position:fixed;bottom:0;left:0;right:0;display:flex;align-items:center;justify-content:space-around;background:#fff;border-top:1px solid #e3e8ef;padding:6px 8px calc(6px + env(safe-area-inset-bottom));z-index:20}.mobile-navigation button{display:flex;flex:1;flex-direction:column;gap:3px;align-items:center;justify-content:center;min-height:52px;padding:4px;border:0;border-radius:0;color:#758296;background:transparent;font-size:12px}.mobile-navigation button.active{color:#3278cf;font-weight:600}.without-footer .workspace-body{padding-bottom:28px}.topbar-leading .icon-button{margin-left:-10px}}

.wechat-topbar{box-sizing:border-box;padding-bottom:0;gap:6px}
.wechat-topbar .topbar-leading{flex:1;gap:8px}
.wechat-topbar .topbar-title{font-size:17px;line-height:1.3;white-space:normal;overflow:visible;overflow-wrap:anywhere}
.wechat-topbar .compact-mark{flex:0 0 28px;width:28px;height:28px}
.wechat-topbar .mobile-service-entry{flex:0 0 44px;min-width:44px;min-height:44px;justify-content:center;padding:0}
.wechat-topbar .mobile-service-entry>text{display:none}

.workspace-scope{margin:-9px 0 14px;padding:11px;border:1px solid #dbe5ef;background:#eff5fa;border-radius:9px}
.scope-eyebrow{display:block;font-size:11px;color:#536b82;margin-bottom:4px}
.scope-choice{display:flex;align-items:center;gap:7px;width:100%;min-height:36px;border:0;margin:0;padding:2px 0;color:#234869;background:transparent;text-align:left;font-size:13px;font-weight:660}
.scope-choice>text{flex:1}.scope-control{box-sizing:border-box;width:100%;min-height:37px;padding:5px 7px;border:1px solid #cbdce9;border-radius:6px;background:#fff;color:#254c71;font:inherit;font-size:13px}.mobile-scope-picker{display:none}
@media(max-width:820px){.mobile-scope-picker{display:block}.mobile-scope-button{display:flex;align-items:center;gap:4px;min-height:38px;font-size:12px}}
</style>
