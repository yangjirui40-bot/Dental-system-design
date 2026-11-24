<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '../../components/AppIcon.vue'
import ClinicOverview from './ClinicOverview.vue'
import { actionsForRecord,staffQuickActions,type StaffTask } from '../../staff-workflow'
import { format } from '../../api'
import {work,resources,loadWorkspace,canUse,goCase,navigate,caseIcons,localDay,dayLabel,clock} from '../../workspace'
const refreshError=ref(''),revision=ref(0)
const role=computed(()=>work.data?.scope.role_code||'')
const apps=computed(()=>resources.value.appointments||[])
const todayApps=computed(()=>apps.value.filter(a=>localDay(a.starts_at)===localDay()))
const waiting=computed(()=>todayApps.value.filter(a=>a.resolution==='arrived'))
const todayText=computed(()=>dayLabel(new Date().toISOString()))
const staffStats=computed(()=>{
 if(['dentist','reception'].includes(role.value))return [{name:'今日有效安排',value:todayApps.value.filter(a=>['booked','arrived','seen'].includes(a.resolution)).length,note:'按当前岗位及门店范围',icon:'calendar'},{name:'已到店待接诊',value:waiting.value.length,note:'由负责牙医确认实际接诊',icon:'staff'},{name:'接续待约',value:(resources.value.followups||[]).filter(a=>!a.closed_at).length,note:'保留阶段与承接责任',icon:'flag'}]
 if(role.value==='manager')return [{name:'已发布出诊',value:(resources.value.duties||[]).filter(a=>a.publication_state==='published').length,note:'当前门店已读取记录',icon:'calendar'},{name:'可用诊疗位',value:(resources.value.operatories||[]).filter(a=>a.resource_state==='active').length,note:'排班与资源共同约束预约',icon:'gear'},{name:'未办接续事项',value:(resources.value.followups||[]).filter(a=>!a.closed_at).length,note:'正常自助，例外协助',icon:'flag'}]
 if(role.value==='finance')return [{name:'费用来源',value:resources.value.cost_sources?.length||0,note:'凭据与每次修订分别保留',icon:'wallet'},{name:'费用分摊',value:resources.value.allocations?.length||0,note:'与原始来源金额守恒',icon:'list'},{name:'齐备声明',value:resources.value.submissions?.length||0,note:'已报齐或明确零额',icon:'checkbox'}]
 if(role.value==='director')return [{name:'费用来源',value:resources.value.cost_sources?.length||0,note:'原始来源及修订分别保留',icon:'wallet'},{name:'齐备声明',value:resources.value.submissions?.length||0,note:'缺报不能作为零成本',icon:'checkbox'},{name:'季度报告',value:resources.value.reports?.length||0,note:'正式确认固化来源版本',icon:'bars'}]
 return [{name:'诊所',value:resources.value.clinics?.length||0,note:'历史业务保留门店归属',icon:'location'},{name:'牙医',value:resources.value.dentists?.length||0,note:'一份身份支持跨店出诊',icon:'staff'},{name:'有效项目标准',value:resources.value.standards?.length||0,note:'草稿与批准版本分开',icon:'list'}]
})
const quickTasks=computed(()=>(staffQuickActions[role.value]||[]).filter(task=>canUse(task.code)))
const pendingTasks=computed<StaffTask[]>(()=>{
 const now=work.data?.server_time||new Date().toISOString()
 const data=resources.value
 const workItems=(key:string,code:string,filter:(row:any)=>boolean)=>{
  if(!canUse(code))return []
  return (data[key]||[]).filter(filter).flatMap(row=>actionsForRecord(code,key,row,role.value,now).map(task=>({
   ...task,subject:row.patient_name||row.label||row.encounter_no||row.treatment_name||row.invoice_no,
  })))
 }
 if(role.value==='reception')return [
  ...workItems('appointments','UC04',row=>row.resolution==='booked'&&Date.parse(row.ends_at)<Date.parse(now)).filter(task=>task.action==='no_show'),
  ...workItems('followups','UC03',row=>!row.closed_at&&(row.contact_progress!=='self_service'||Date.parse(row.next_contact_at)<Date.parse(now))),
 ].slice(0,6)
 if(role.value==='dentist')return [
  ...workItems('appointments','UC04',row=>row.resolution==='arrived'),
  ...workItems('encounters','UC05',row=>!row.latest_signature_state||row.latest_signature_state==='draft').filter(task=>task.action==='draft'),
 ].slice(0,6)
 if(role.value==='manager')return [
  ...workItems('allocations','UC11',row=>row.review_state==='pending'),
  ...workItems('submissions','UC11',row=>row.review_state==='pending'),
  ...workItems('followups','UC03',row=>!row.closed_at&&(row.contact_progress!=='self_service'||Date.parse(row.next_contact_at)<Date.parse(now))),
 ].slice(0,6)
 if(role.value==='director')return workItems('standard_drafts','UC10',()=>true).filter(task=>task.action==='approve').slice(0,6)
 return []
})
function openTask(task:StaffTask){
 const params:Record<string,string|number>={}
 if(task.action)params.action=task.action
 if(task.dataset)params.dataset=task.dataset
 if(task.id)params.id=task.id
 if(task.code==='UC03'&&task.dataset==='followups')navigate('/pages/operations/index?'+Object.entries({case:'UC03',...params}).map(([key,value])=>key+'='+encodeURIComponent(value)).join('&'))
 else goCase(task.code,params)
}
function agendaLabel(row:any){
 return actionsForRecord('UC04','appointments',row,role.value,work.data?.server_time||new Date().toISOString())[0]?.label||'查看安排'
}
function openAgenda(row:any){
 const next=actionsForRecord('UC04','appointments',row,role.value,work.data?.server_time||new Date().toISOString())[0]
 if(next)openTask(next)
 else goCase('UC04',{id:row.id})
}

const recent=computed(()=>[...apps.value].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at)||b.id-a.id).slice(0,6))
const canCompareClinics=computed(()=>['manager','business','director','finance'].includes(role.value))
const agenda=computed(()=>todayApps.value.filter(a=>['booked','arrived','seen'].includes(a.resolution)).sort((a,b)=>a.starts_at.localeCompare(b.starts_at)).slice(0,8))
async function refresh(){refreshError.value='';try{await loadWorkspace(true);revision.value++}catch(e:any){refreshError.value=e.message}}
</script>

<template>
 <view class="staff-home">
  <view class="home-welcome">
   <view><text class="staff-date">{{todayText}} · {{work.data?.scope.clinic_name||'集团范围'}}</text><text class="staff-title">{{work.data?.scope.role_name}}工作台</text></view>
   <button class="quiet" @click="refresh" :disabled="work.loading">刷新工作台</button>
  </view>
  <view v-if="refreshError" class="error">{{refreshError}}</view>
  <ClinicOverview v-if="canCompareClinics" :revision="revision"/>
  <view class="staff-overview"><view v-for="stat in staffStats" :key="stat.name" class="overview-item"><text>{{stat.name}}</text><text class="overview-value">{{stat.value}}</text></view></view>
  <view class="staff-columns">
   <view class="staff-main">
    <view v-if="canUse('UC03')" class="staff-panel latest-appointment-panel">
     <view class="panel-head"><text>最新预约</text><button class="row-action" @click="goCase('UC03')">打开预约工作台 <AppIcon name="right" :size="15"/></button></view>
     <view v-for="record in recent" :key="record.id" class="staff-row latest-appointment">
      <view><text class="visitor-name">{{record.patient_name}} · {{record.clinic_name}}</text><text class="panel-meta">{{dayLabel(record.starts_at)}} {{clock(record.starts_at)}} · {{record.dentist_name}} · {{record.appointment_no}}</text></view>
      <text class="agenda-badge">{{format(record.resolution)}}</text>
      <button class="row-action" @click="goCase('UC03',{id:record.id})">查看 <AppIcon name="right" :size="14"/></button>
     </view>
     <text v-if="!recent.length" class="empty-row">当前门店暂无预约。可在侧栏切换工作门店。</text>
    </view>
    <view class="staff-panel">
     <view class="panel-head"><text>待我办理</text><text class="panel-meta">{{pendingTasks.length}} 项</text></view>
     <view v-for="task in pendingTasks" :key="task.code+'-'+task.action+'-'+task.id" class="staff-row task-row"><text class="task-subject">{{task.subject||task.label}}</text><button class="row-action" @click="openTask(task)">{{task.label}} <AppIcon name="right" :size="14"/></button></view>
     <text v-if="!pendingTasks.length" class="empty-row">当前没有需要处理的记录。</text>
    </view>
    <view v-if="canUse('UC04')" class="staff-panel">
     <view class="panel-head"><text>今日接诊</text><button class="row-action" @click="goCase('UC04')">查看全部 <AppIcon name="right" :size="14"/></button></view>
     <view v-if="agenda.length" class="agenda-row agenda-head"><text>时间</text><text>就诊人 / 接诊医生</text><text>状态</text><text>操作</text></view>
     <view v-for="record in agenda" :key="record.id" class="staff-row agenda-row"><text class="agenda-clock">{{clock(record.starts_at)}}</text><view><text class="visitor-name">{{record.patient_name}}</text><text class="panel-meta">{{record.clinic_name}} · {{record.dentist_name}}</text></view><text class="agenda-badge">{{format(record.resolution)}}</text><button class="row-action" @click="openAgenda(record)">{{agendaLabel(record)}}</button></view>
     <text v-if="!agenda.length" class="empty-row">今天暂无就诊安排。</text>
    </view>
   </view>
   <view class="staff-panel staff-action-panel">
    <view class="panel-head"><text>常用操作</text></view>
    <view class="staff-shortcuts"><button v-if="canUse('UC09')" class="roster-shortcut" @click="goCase('UC09',{view:'roster'})"><AppIcon name="staff" :size="18"/><text class="shortcut-label">查看医生名录</text><AppIcon name="right" :size="14" color="#758296"/></button><button v-for="task in quickTasks" :key="task.label" @click="openTask(task)"><AppIcon :name="caseIcons[task.code]" :size="18"/><text class="shortcut-label">{{task.label}}</text><AppIcon name="right" :size="14" color="#758296"/></button></view>
   </view>
  </view>
 </view>
</template>

<style scoped>
.staff-home{min-width:0;color:#253347}
.home-welcome{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 18px}
.staff-date{display:block;color:#526378;font-size:13px}.staff-title{display:block;font-size:26px;font-weight:650;line-height:1.5;margin-top:4px}
.staff-overview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:#e0e7ef;border:1px solid #e0e7ef;border-radius:10px;overflow:hidden;margin-bottom:18px}
.overview-item{min-width:0;background:#fff;padding:12px 16px;font-size:13px;color:#526378}
.overview-value{display:block;margin-top:4px;font-size:24px;line-height:1.2;color:#253347;font-weight:650}
.staff-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,32%);align-items:start;gap:16px}
.staff-main{display:grid;gap:16px;min-width:0}.staff-panel{min-width:0;background:#fff;border:1px solid #e0e7ef;border-radius:10px;overflow:hidden}
.panel-head{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 15px;min-height:48px;border-bottom:1px solid #e5ebf2;font-size:16px;font-weight:650}
.panel-meta,.agenda-head{font-size:12px;color:#526378;font-weight:400}.empty-row{display:block;padding:17px 15px;color:#526378;font-size:13px}
.staff-row{padding:9px 15px;border-top:1px solid #e5ebf2;min-height:46px;font-size:14px}
.staff-row:first-of-type{border-top:0}.task-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.row-action{display:flex;align-items:center;gap:2px;padding:3px 0;font-size:13px;background:transparent;color:#235f9d;border:0;min-height:36px;white-space:nowrap;margin:0}
.agenda-row{display:grid;grid-template-columns:60px minmax(0,1fr) minmax(48px,auto) auto;align-items:center;column-gap:10px}.agenda-head{background:#f6f8fb;padding:8px 15px}
.agenda-clock{font-weight:650;font-variant-numeric:tabular-nums}.visitor-name{display:block;overflow-wrap:anywhere}.agenda-badge{color:#235f9d;font-size:12px}
.staff-shortcuts{padding:0 12px}.staff-shortcuts>button{display:flex;align-items:center;gap:8px;min-height:44px;border:0;border-bottom:1px solid #e5ebf2;border-radius:0;background:#fff;width:100%;font-size:14px;padding:8px 3px;margin:0;text-align:left}
.staff-shortcuts>button:last-child{border-bottom:0}.shortcut-label{flex:1;min-width:0;text-align:left}
@media(max-width:1090px){.staff-columns{grid-template-columns:minmax(0,1fr)}.staff-shortcuts{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:0 12px}}
@media(max-width:580px){.overview-item{padding:10px 8px;font-size:12px}.staff-title{font-size:22px}.agenda-row{grid-template-columns:45px minmax(0,1fr) auto;gap:6px}.agenda-row>*:last-child{grid-column:2/-1}.agenda-head>*:last-child{display:none}}

.latest-appointment{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:9px}
.latest-appointment .panel-meta{display:block;overflow-wrap:anywhere}
.home-welcome{padding:15px 18px;background:#f0f5fa;border-radius:10px;border:1px solid #dce7f1}
</style>
