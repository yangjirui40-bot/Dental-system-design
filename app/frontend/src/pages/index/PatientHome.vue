<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '../../components/AppIcon.vue'
import { format } from '../../api'
import {work,resources,canUse,goCase,navigate,dayLabel,clock} from '../../workspace'
const role=computed(()=>work.data?.scope.role_code||'patient')
const apps=computed(()=>resources.value.appointments||[])
const upcoming=computed(()=>apps.value.filter(a=>a.resolution==='unfulfilled'||(['booked','arrived'].includes(a.resolution)&&new Date(a.ends_at).getTime()>=new Date(work.data?.server_time||Date.now()).getTime())).sort((a,b)=>Number(b.resolution==='unfulfilled')-Number(a.resolution==='unfulfilled')||new Date(a.starts_at).getTime()-new Date(b.starts_at).getTime()))
const next=computed(()=>upcoming.value[0])
const awaitingVerification=computed(()=>apps.value.filter(a=>['booked','arrived'].includes(a.resolution)&&new Date(a.ends_at).getTime()<new Date(work.data?.server_time||Date.now()).getTime()).length)
const readyPhases=computed(()=>(resources.value.phases||[]).filter(p=>['ready','waiting','booked'].includes(p.progress_outcome)))

const actions=[
 {code:'UC03',name:'我的预约',note:'改期、取消和到店报到',icon:'calendar',params:{}},
 {code:'UC14',name:'费用账单',note:'查看结算明细',icon:'wallet',params:{dataset:'invoices'}},
 {code:'UC14',name:'治疗计划',note:'查看阶段及下一步',icon:'flag',params:{dataset:'phases'}},
 {code:'UC01',name:'就诊资料',note:'联系人和过敏信息',icon:'person',params:{}},
] as Array<{code:string,name:string,note:string,icon:string,params:Record<string,string>}>
const recentInvoice=computed(()=>resources.value.invoices?.[0])
function openNext(){if(next.value)goCase('UC03',{id:next.value.id})}
</script>

<template>
 <view class="patient-home home-welcome">
  <view class="visit-owner">
   <view><text class="muted">当前账号</text><text class="owner-name">{{work.data?.account.display_name}}</text></view>
   <button class="plain phone-tap" @click="navigate('/pages/me/index')">{{role==='representative'?'查看授权':'我的资料'}} <AppIcon name="right" :size="14"/></button>
  </view>
  <view class="patient-panel main-visit">
   <view class="panel-head"><text>{{next?.resolution==='unfulfilled'?'待重新安排':'下一次就诊'}}</text><text v-if="next" class="visit-state">{{format(next.resolution)}}</text></view>
   <template v-if="next">
    <text class="visit-time">{{dayLabel(next.starts_at)}} {{clock(next.starts_at)}}–{{clock(next.ends_at)}}</text>
    <text class="visit-location">{{next.clinic_name}} · {{next.dentist_name}}</text>
    <button class="plain visit-action phone-tap" @click="openNext">{{next.resolution==='unfulfilled'?'重新安排':next.resolution==='arrived'?'查看报到状态':'查看预约详情'}} <AppIcon name="right" :size="15"/></button>
   </template>
   <text v-else class="panel-empty">{{awaitingVerification?'有已到期的安排待门店核实':'暂无即将开始的预约'}}</text>
  </view>
  <view v-if="canUse('UC02')" class="patient-panel booking-entry">
   <view><text class="book-title">预约就诊</text><text class="book-note">选择门店、医生与就诊时段</text><button class="primary patient-start-booking phone-tap" @click="goCase('UC02')">开始预约 <AppIcon name="right" :size="14" color="#fff"/></button><button class="plain directory-entry phone-tap" @click="navigate('/pages/directory/index')">门店与医生 <AppIcon name="right" :size="14"/></button></view>
   <image class="entry-photo" src="/static/images/clinic-scene.jpg" mode="aspectFill" aria-label="诊所环境示意"/>
  </view>
  <view class="patient-section">
   <text class="section-title">常用服务</text>
   <view class="patient-panel service-list">
    <button v-for="item in actions.filter(a=>canUse(a.code))" :key="item.name" class="service-row" @click="goCase(item.code,item.params)">
     <view class="service-icon"><AppIcon :name="item.icon" :size="22"/></view>
     <view class="service-copy"><text class="service-name">{{item.name}}</text><text class="service-note">{{item.note}}</text></view>
     <AppIcon name="right" :size="16" color="#758296"/>
    </button>
   </view>
  </view>
  <view v-if="canUse('UC14')&&(readyPhases.length||recentInvoice)" class="patient-section">
   <text class="section-title">近期就诊动态</text>
   <view class="patient-panel service-list">
    <button v-for="phase in readyPhases.slice(0,2)" :key="phase.id" class="service-row" @click="goCase('UC14',{dataset:'phases'})"><view class="service-copy"><text class="service-name">{{phase.phase_title}}</text><text class="service-note">{{format(phase.progress_outcome)}}</text></view><AppIcon name="right" :size="16" color="#758296"/></button>
    <button v-if="recentInvoice" class="service-row" @click="navigate('/pages/invoice/index?id='+recentInvoice.id)"><view class="service-copy"><text class="service-name">最近的费用账单</text><text class="service-note">{{recentInvoice.invoice_no}}</text></view><AppIcon name="right" :size="16" color="#758296"/></button>
   </view>
  </view>
 </view>
</template>

<style scoped>
.patient-home{max-width:760px;margin:0 auto;min-width:0;color:#253347}
.visit-owner{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:0 0 14px}
.visit-owner .muted{display:block;font-size:12px}.owner-name{display:block;font-size:20px;font-weight:650;margin-top:2px}
.plain{display:flex;align-items:center;gap:4px;padding:0;border:0;background:transparent;color:#235f9d;font-size:14px;margin:0}
.phone-tap{min-height:44px}
.patient-panel{box-sizing:border-box;background:#fff;border:1px solid #e0e7ef;border-radius:12px;min-width:0}
.main-visit{padding:15px 16px 8px;border-top:3px solid #3278cf}
.panel-head{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:14px;font-weight:650}
.visit-state{padding:3px 8px;font-size:12px;border-radius:12px;background:#edf5ff;color:#235f9d}
.visit-time{display:block;margin:9px 0 5px;font-size:18px;font-weight:650;line-height:1.45}
.visit-location,.panel-empty,.book-note,.service-note{display:block;color:#526378;font-size:13px;line-height:1.6}
.panel-empty{margin:12px 0 9px}.visit-action{margin-top:4px}
.booking-entry{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 15px;margin-top:12px}
.booking-entry>view{min-width:0}.entry-photo{width:110px;height:101px;border-radius:8px;object-fit:cover;flex-shrink:0}
.book-title,.section-title{display:block;font-size:17px;font-weight:650}.book-note{margin:3px 0 8px}
.patient-start-booking{display:inline-flex;min-width:115px;justify-content:center;align-items:center;gap:4px;margin:0;padding:7px 11px;font-size:14px}
.directory-entry{margin-top:3px;font-size:13px}.patient-section{margin-top:18px}.section-title{margin:0 0 8px 1px}
.service-list{padding:0 13px}.service-row{width:100%;display:flex;align-items:center;gap:10px;padding:9px 0;margin:0;min-height:62px;border:0;border-bottom:1px solid #e5ebf2;border-radius:0;text-align:left;background:#fff}
.service-row:last-child{border:0}.service-icon{display:flex;align-items:center;justify-content:center;width:36px;height:36px;background:#edf5ff;border-radius:8px;flex-shrink:0}
.service-copy{flex:1;min-width:0}.service-name{display:block;font-size:14px;font-weight:600}.service-note{font-size:12px}
@media(max-width:360px){.entry-photo{width:85px;height:96px}.service-note{overflow-wrap:anywhere}}
</style>
