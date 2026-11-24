<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import AppIcon from '../../components/AppIcon.vue'
import {request} from '../../api'
import {canUse,caseUrl,goCase,localDay,money,selectScopeById,work,type Row} from '../../workspace'

const props=defineProps<{revision:number}>()
const clinics=ref<Row[]>([])
const selectedId=ref(0)
const quarter=ref<Row|null>(null)
const error=ref('')
const pending=ref(false)
const current= computed(()=>clinics.value.find(c=>c.id===selectedId.value))
const closed=computed(()=>current.value?.closed_on&&current.value.closed_on<localDay())
let sequence=0

async function load(){
 const generation=++sequence
 pending.value=true
 error.value=''
 try{
  const report=await request('/api/clinic-overview')
  if(generation!==sequence)return
  clinics.value=report.clinics
  quarter.value=report.quarter
  if(!current.value)selectedId.value=work.data?.scope.clinic_id||clinics.value[0]?.id||0
 }catch(problem:unknown){if(generation===sequence)error.value=problem instanceof Error?problem.message:'暂时无法读取门店'}
 finally{if(generation===sequence)pending.value=false}
}

async function open(code:string) {
 if(!current.value)return
 const clinic=current.value.id
 const scope=work.data?.scope
 if(scope?.scope_kind==='group'||scope?.clinic_id===clinic){goCase(code,{clinic});return}
 const assigned=work.data?.scopes.find(item=>item.role_code===scope?.role_code&&item.clinic_id===clinic)
 if(!assigned)return
 try{await selectScopeById(assigned.id,caseUrl(code,{clinic}))}
 catch(problem:unknown){error.value=problem instanceof Error?problem.message:'切换门店失败'}
}
onMounted(load)
watch(()=>props.revision,load)
</script>

<template>
 <view class="chain-overview">
  <view class="chain-top">
   <view><text class="chain-title">门店运营总览</text><text class="chain-caption">按授权查看各门店的医生、今日预约和经营</text></view>
   <view class="chain-heading-actions">
    <button v-if="canUse('UC09')&&work.data?.scope.scope_kind==='group'" class="quiet cross-schedule-entry" @click="goCase('UC09',{view:'cross'})"><AppIcon name="calendar" :size="16"/> 跨店出诊</button>
    <button v-if="canUse('UC07')" class="quiet" @click="goCase('UC07')">门店档案</button>
   </view>
  </view>
  <view v-if="error" class="error">{{error}}</view>
  <view v-if="clinics.length" class="chain-grid">
   <view class="branch-list" aria-label="选择查看的门店">
    <button v-for="branch in clinics" :key="branch.id" class="chain-branch" :class="{active:branch.id===selectedId}" :aria-pressed="branch.id===selectedId" @click="selectedId=branch.id">
     <AppIcon name="location" :size="15"/><text>{{branch.clinic_name}}</text><text class="branch-count">{{branch.doctors.length}} 位</text>
    </button>
   </view>
   <view v-if="current" class="chain-detail">
    <view class="chain-detail-head">
     <view><text class="branch-title">{{current.clinic_name}}</text><text class="chain-caption">{{current.postal_address}}</text></view>
     <text v-if="closed" class="closed-label">已停业</text>
    </view>
    <view class="chain-metrics">
     <view><text>今日预约</text><text>{{current.appointments_today}}</text></view>
     <view><text>近期在职出诊医生</text><text>{{current.doctors.length}}</text></view><view><text>关联患者</text><text>{{current.patients}}</text></view>
     <view v-if="current.revenue!==undefined"><text>{{quarter?.quarter_no}} 季度结算收入</text><text>¥{{money(current.revenue)}}</text></view>
    </view>
    <view class="chain-roster"><text v-for="doctor in current.doctors" :key="doctor.id">{{doctor.full_name}}</text><text v-if="!current.doctors.length" class="chain-caption">近期没有已发布出诊</text></view>
    <view class="chain-detail-actions">
     <button v-if="canUse('UC03')" class="quiet branch-appointments-entry" @click="open('UC03')">查看该店预约</button><button v-if="canUse('UC09')" class="quiet branch-calendar-entry" @click="open('UC09')">查看该店排班</button>
     <button v-if="canUse('UC12')" class="primary branch-finance-entry" @click="open('UC12')">查看该店经营</button>
    </view>
   </view>
  </view>
  <text v-else class="chain-caption">{{pending?'正在加载门店…':'当前权限范围内暂无门店。'}}</text>
 </view>
</template>

<style scoped>
.chain-overview{margin-bottom:19px;background:#fff;border:1px solid #cfdfec;border-radius:11px;overflow:hidden}
.chain-top{display:flex;justify-content:space-between;align-items:center;gap:15px;padding:16px 18px;background:#eaf3fa;border-bottom:1px solid #dce8f1}
.chain-title,.branch-title{display:block;color:#203e5c;font-size:19px;font-weight:680}.chain-caption{display:block;color:#537087;font-size:12px;margin-top:4px;line-height:1.55}
.chain-heading-actions,.chain-detail-actions{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.chain-heading-actions button,.chain-detail-actions button{display:flex;gap:5px;align-items:center;margin:0;font-size:12px;min-height:36px;padding:6px 11px}
.chain-grid{display:grid;grid-template-columns:minmax(156px,25%) minmax(0,1fr)}
.branch-list{padding:8px;background:#f6f8fb;border-right:1px solid #e1e9ef;max-height:290px;overflow-y:auto}
.chain-branch{display:flex;align-items:center;gap:7px;width:100%;margin:0;border:0;font-size:12px;min-height:37px;padding:4px 8px;background:transparent;text-align:left;color:#456078}
.chain-branch.active{background:#e0eef9;color:#164b7c;font-weight:680}
.branch-count{margin-left:auto;white-space:nowrap;color:#496c86;font-size:11px}
.chain-detail{min-width:0;padding:15px 17px}
.chain-detail-head{display:flex;justify-content:space-between;align-items:flex-start;gap:5px}
.branch-title{font-size:18px}.closed-label{font-size:12px;color:#6a4b24}
.chain-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(142px,1fr));gap:8px;margin:13px 0 10px;padding:10px 0;border-block:1px solid #e4ebf2}
.chain-metrics>view>text{display:block;font-size:12px;color:#566c82}.chain-metrics>view>text:last-child{font-size:20px;font-weight:680;color:#284f76;margin-top:4px}
.chain-roster{display:flex;flex-wrap:wrap;font-size:12px;gap:5px 11px;margin-bottom:14px;color:#435b73}
@media(max-width:680px){.chain-top{flex-wrap:wrap}.chain-grid{grid-template-columns:minmax(0,1fr)}.branch-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));max-height:155px;border:0;border-bottom:1px solid #e1e9ef}.chain-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.chain-metrics>view>text:last-child{font-size:17px}}
</style>
