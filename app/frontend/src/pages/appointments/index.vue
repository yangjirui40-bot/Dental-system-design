<script setup lang="ts">
import {ref,computed} from 'vue'
import {onShow,onLoad} from '@dcloudio/uni-app'
import WorkspaceShell from '../../components/WorkspaceShell.vue'
import AppIcon from '../../components/AppIcon.vue'
import DateRangeQuery from '../../components/DateRangeQuery.vue'
import {request,uuid,format} from '../../api'
import {work,personal,requireWorkspace,loadWorkspace,canUse,goCase,navigate,localDay,dayLabel,clock,money,queryString,selectScopeById,caseUrl,type Row} from '../../workspace'
const tab=ref('all'),query=ref(''),fromDate=ref(''),toDate=ref('')
const visible=ref<Row[]>([]),selected=ref<any>(null),busy=ref(false),error=ref(''),notice=ref('')
const cancelOpen=ref(false),cancelReason=ref(''),requestedId=ref(0)
const order=ref('created'),cursor=ref(''),lookup=ref<Row|null>(null),looking=ref(false),lookupMessage=ref('')
const sortLabels=[{key:'created',label:'最新创建'},{key:'visit-desc',label:'就诊时间 ↓'},{key:'visit-asc',label:'就诊时间 ↑'}]
const tabs=[{key:'all',name:'全部预约'},{key:'current',name:'待就诊'},{key:'exceptions',name:'待重新安排'},{key:'history',name:'历史'}]
const appliedBase={from_date:'',to_date:'',q:''}
let applied={...appliedBase},pageRequest=0,cancelKey='',cancelRaw=''
const staffScope=computed(()=>work.data?.scope.clinic_name||'当前授权范围')
const canLocate=computed(()=>!personal.value&&['reception','manager'].includes(work.data?.scope.role_code))
onLoad((q:any)=>requestedId.value=Number(q?.id||0))
onShow(async()=>{
 if(!await requireWorkspace('UC03'))return
 await queryRecords(false,true)
 if(requestedId.value){await inspect(requestedId.value);requestedId.value=0}
})
const a=computed<Row|null>(()=>selected.value?.appointment||null)
const changeable=computed(()=>a.value&&['booked','arrived','unfulfilled'].includes(a.value.resolution)&&canUse('UC03'))
const canArrive=computed(()=>a.value?.resolution==='booked'&&localDay(a.value.starts_at)===localDay()&&canUse('UC04'))
const timeline=computed(()=>a.value?[{id:'created',event_kind:'created',occurred_at:a.value.created_at,reason_description:'预约安排已保存',actor_name:channel(a.value.request_channel)},...(selected.value.events||[])]:[])
const eventNames:Record<string,string>={created:'预约建立',arrive:'到店报到',start:'牙医确认接诊',cancel:'预约取消',reschedule:'改期接续',leave:'到店后未接诊离开',no_show:'现场核实未到',stop:'机构停诊',replace:'出诊引用调整'}
function channel(value:string){return ({patient_portal:'患者本人',representative_portal:'授权代办人',reception:'前台协助',clinic_manager:'门店主管'} as Record<string,string>)[value]||'原记录办理主体'}
async function inspect(id:number){busy.value=true;error.value='';try{selected.value=await request('/api/appointments/'+id);cancelOpen.value=false;uni.pageScrollTo({scrollTop:0,duration:0})}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function refresh(){
 const id=a.value?.id
 await loadWorkspace(true)
 await queryRecords(false,true)
 if(id)await inspect(id)
}
async function queryRecords(append=false,retain=false){
 const req=++pageRequest
 busy.value=true
 error.value=''
 if(!append){lookup.value=null;lookupMessage.value=''}
 try{
  const filters=append||retain?applied:{from_date:fromDate.value,to_date:toDate.value,q:query.value.trim()}
  if(filters.from_date&&filters.to_date&&filters.from_date>filters.to_date)throw Error('开始日期不能晚于结束日期')
  const result=await request('/api/appointment-queue?'+queryString({...filters,order:order.value,tab:tab.value,...(append&&cursor.value?{cursor:cursor.value}:{})}))
  if(req!==pageRequest)return
  applied={...filters}
  visible.value=append?[...visible.value,...result.items]:result.items
  cursor.value=result.next||''
 }catch(e:any){if(req===pageRequest)error.value=e.message}
 finally{if(req===pageRequest)busy.value=false}
}
function changeTab(key:string){tab.value=key;selected.value=null;cursor.value='';queryRecords(false,true)}
function changeOrder(index:number){order.value=sortLabels[index]?.key||'created';cursor.value='';queryRecords(false,true)}
async function clearQuery(){query.value='';fromDate.value='';toDate.value='';await queryRecords()}
async function loadMore(){if(cursor.value&&!busy.value)await queryRecords(true)}
async function locate(){
 looking.value=true;lookup.value=null;lookupMessage.value=''
 try{lookup.value=await request('/api/appointment-location?number='+encodeURIComponent(query.value.trim()))}
 catch(e:any){lookupMessage.value=e.message}
 finally{looking.value=false}
}
async function openLocated(){
 if(!lookup.value)return
 const record=lookup.value
 try {
  if(record.scope_id===work.data?.scope.id)await inspect(record.id)
  else await selectScopeById(record.scope_id,caseUrl('UC03',{id:record.id}))
 }catch(e:any){error.value=e.message}
}
async function cancel(){if(!a.value||!cancelReason.value.trim()){error.value='请填写本次取消原因。';return}busy.value=true;error.value='';const data={action:'cancel',id:a.value.id,row_version:a.value.row_version,reason:cancelReason.value.trim()};const raw=JSON.stringify(data);if(raw!==cancelRaw){cancelRaw=raw;cancelKey=uuid()}try{await request('/api/use-cases/UC03',data,cancelKey);cancelOpen.value=false;notice.value='本次预约已取消，原安排与原因继续保留。';cancelKey='';cancelRaw='';await refresh()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function arrive(){if(!a.value)return;const confirmed=await new Promise<boolean>(resolve=>uni.showModal({title:'确认已经到店',content:'请确认你已实际到达'+a.value?.clinic_name+'。报到更新候诊信息，实际接诊由牙医另行确认。',success:r=>resolve(r.confirm)}));if(!confirmed)return;busy.value=true;error.value='';try{await request('/api/use-cases/UC04',{action:'arrive',appointment_id:a.value.id},uuid());notice.value='已记录到店，候诊信息已更新。';await refresh()}catch(e:any){error.value=e.message}finally{busy.value=false}}
function openFollowups(){navigate('/pages/operations/index?case=UC03&dataset=followups')}
function receptionCase(action:string){if(a.value)goCase('UC04',{id:a.value.id,action})}
function reschedule(){if(a.value)navigate('/pages/appointments/book?appointment='+a.value.id)}
</script>
<template><WorkspaceShell v-if="work.data" :title="personal?'我的预约':'预约管理'" active="UC03" back>
 <view class="appointment-page" :class="{'has-selection':!!selected,'staff-queue':!personal}">
  <view class="appointment-header">
   <view><text class="page-title">{{personal?'我的预约':'预约工作台'}}</text><text class="page-caption">{{personal?'按状态查看安排和就诊历史':staffScope+' · 当前岗位的预约记录'}}</text></view>
   <view class="appointment-actions">
    <button class="quiet refresh-appointments" :disabled="busy" @click="refresh().catch(e=>error=e.message)"><AppIcon name="refreshempty" :size="16"/>刷新</button>
    <button v-if="canUse('UC02')" class="primary new-appointment" @click="goCase('UC02')"><AppIcon name="plusempty" :size="18" color="#fff"/>{{personal?'预约就诊':'协助预约'}}</button>
   </view>
  </view>
  <view v-if="error" class="error">{{error}}</view><view v-if="notice" class="notice-result">{{notice}}</view>
  <view class="appointments-layout">
   <view class="appointments-master surface">
    <view class="appointment-tabs"><button v-for="item in tabs" :key="item.key" :class="{active:tab===item.key}" @click="changeTab(item.key)">{{item.name}}</button></view>
    <view class="appointment-search">
     <view class="queue-toolbar">
      <view class="search-input"><AppIcon name="search" :size="17" color="#53687b"/><input v-model="query" aria-label="搜索预约" :placeholder="personal?'门店、医生或预约号':'患者、医生或预约号'" @confirm="queryRecords()"/></view>
      <button class="quiet queue-search" :disabled="busy" @click="queryRecords()">搜索</button>
      <picker :range="sortLabels" range-key="label" @change="changeOrder(Number($event.detail.value))"><button class="quiet sort-appointments" aria-label="预约排序">{{sortLabels.find(sort=>sort.key===order)?.label}} <AppIcon name="down" :size="14"/></button></picker>
     </view>
     <DateRangeQuery v-model:from="fromDate" v-model:to="toDate" :busy="busy" label="就诊日期" @query="queryRecords()" @clear="clearQuery"/>
     <view v-if="!personal" class="queue-links">
      <button v-if="canLocate" class="text-button cross-lookup" :disabled="looking||!query.trim()" @click="locate">按预约号跨店查找</button>
      <button v-if="canUse('UC03')" class="text-button followup-entry" @click="openFollowups">例外待约</button>
     </view>
     <view v-if="lookup" class="lookup-result"><text>预约在{{lookup.clinic_name}}</text><button class="quiet open-located" @click="openLocated">查看这笔预约</button></view>
     <text v-if="lookupMessage" class="loaded-caption">{{lookupMessage}}</text>
    </view>
    <view v-if="!personal" class="queue-columns"><text>患者 / 预约号</text><text>门店 / 接诊医生</text><text>就诊时间</text><text>状态 / 创建时间</text></view>
    <view class="appointment-records">
     <button v-for="row in visible" :key="row.id" class="appointment-record" :class="{selected:a?.id===row.id}" @click="inspect(row.id)">
      <template v-if="personal">
       <view class="record-top"><text class="record-date">{{dayLabel(row.starts_at)}}</text><text class="status-tag" :class="{warning:row.resolution==='unfulfilled'}">{{format(row.resolution)}}</text></view>
       <text class="record-time">{{clock(row.starts_at)}}—{{clock(row.ends_at)}}</text>
       <text class="record-clinic">{{row.clinic_name}} · {{row.dentist_name}}</text>
       <view class="record-bottom"><text>{{row.appointment_no}}</text><AppIcon name="right" :size="16" color="#758296"/></view>
      </template>
      <template v-else>
       <view><text class="queue-primary">{{row.patient_name}}</text><text class="queue-secondary queue-number">{{row.appointment_no}}</text></view>
       <view><text class="queue-primary">{{row.clinic_name}}</text><text class="queue-secondary">{{row.dentist_name}} · {{row.operatory_name}}</text></view>
       <view><text class="queue-primary">{{dayLabel(row.starts_at)}}</text><text class="queue-secondary">{{clock(row.starts_at)}}–{{clock(row.ends_at)}}</text></view>
       <view><text class="status-tag" :class="{warning:row.resolution==='unfulfilled'}">{{format(row.resolution)}}</text><text class="queue-secondary">创建 {{dayLabel(row.created_at).split(' 周')[0]}} {{clock(row.created_at)}}</text></view>
      </template>
     </button>
     <view v-if="!visible.length" class="appointments-empty"><AppIcon name="calendar" :size="31" color="#758296"/><text>{{busy?'正在读取预约…':'当前筛选下没有预约记录'}}</text><text v-if="!busy&&!personal">可切换门店、调整筛选，或按完整预约号跨店定位。</text></view>
    </view>
    <button v-if="cursor" class="load-more" :disabled="busy" @click="loadMore">加载更多预约</button>
    <text class="loaded-caption">已显示 {{visible.length}} 条预约</text>
   </view>
 <view v-if="selected&&a" class="appointment-detail"><view v-if="!personal&&canUse('UC04')" class="staff-appointment-actions">
<button v-if="a.resolution==='arrived'" class="quiet small" @click="receptionCase('leave')">登记到店未接诊</button>
<button v-if="a.resolution==='booked'&&Date.parse(a.ends_at)<Date.parse(work.data?.server_time||'')" class="quiet small" @click="receptionCase('no_show')">核实未到</button>
</view><button class="back-list" @click="selected=null"><AppIcon name="left" :size="17"/><text>返回预约列表</text></button><view class="detail-card surface"><view class="detail-card-header"><text class="detail-label">预约详情</text><text class="status-tag" :class="{warning:a.resolution==='unfulfilled'}">{{format(a.resolution)}}</text></view><view class="detail-main"><text class="detail-clinic">{{a.clinic_name}}</text><text class="detail-time">{{dayLabel(a.starts_at)}} {{clock(a.starts_at)}}—{{clock(a.ends_at)}}</text><text class="detail-address">{{a.postal_address}}</text><view class="detail-grid"><view><text>就诊人</text><text>{{a.patient_name}}</text></view><view><text>接诊牙医</text><text>{{a.dentist_name}}</text></view><view><text>诊疗资源</text><text>{{a.operatory_name}}</text></view><view><text>办理方式</text><text>{{channel(a.request_channel)}}</text></view></view><view class="requested-projects"><text>拟治疗项目</text><text>{{selected.requested_items.map((item:Row)=>item.request_description).join('、')||'按原就诊诉求安排'}}</text></view><view v-if="a.presenting_request" class="requested-projects"><text>就诊诉求</text><text>{{a.presenting_request}}</text></view><view v-if="a.resolution==='unfulfilled'" class="detail-warning"><AppIcon name="info" :size="19"/><text>原安排因机构原因不可履行，请重新选择完整时段；原约及接续责任继续保留。</text></view><view v-if="a.resolution==='arrived'" class="detail-info"><AppIcon name="staff" :size="19"/><text>已记录到店。到店不等于已接诊，实际就诊由负责牙医确认。</text></view><view v-if="changeable||canArrive" class="detail-actions"><button v-if="canArrive" class="primary" :disabled="busy" @click="arrive">我已到店，办理报到</button><button v-if="changeable" :disabled="busy" @click="reschedule">{{a.resolution==='unfulfilled'?'重新安排':'改期'}}</button><button v-if="changeable" class="cancel-action" :disabled="busy" @click="cancelOpen=true;cancelReason='';error=''">取消预约</button></view><view v-if="selected.invoice" class="invoice-preview"><view><text>已生效业务结算</text><text class="record-meta">{{selected.invoice.invoice_no}} · 版本 {{selected.invoice.revision_no}}</text></view><text>¥{{money(selected.invoice.total_amount)}}</text><button class="text-button" @click="goCase(canUse('UC14')?'UC14':'UC06',{dataset:'invoices',id:selected.invoice.id})">查看明细</button></view><text v-else-if="selected.encounter" class="detail-caption">实际接诊已确认，尚无生效结算；这不表示本次费用为零。</text><text class="detail-number">预约编号 {{a.appointment_no}}</text></view></view><view v-if="selected.previous||selected.next" class="surface continuity-links"><text class="section-title-small">改约接续</text><button v-if="selected.previous" @click="inspect(selected.previous.id)"><view><text>查看原预约</text><text>{{selected.previous.appointment_no}}</text></view><AppIcon name="left" :size="16"/></button><button v-if="selected.next" @click="inspect(selected.next.id)"><view><text>查看接续预约</text><text>{{selected.next.appointment_no}}</text></view><AppIcon name="right" :size="16"/></button></view><view class="surface appointment-timeline"><text class="section-title-small">办理时间线</text><view v-for="event in timeline" :key="event.id" class="timeline-row"><view class="timeline-point"></view><view><view class="timeline-heading"><text>{{eventNames[event.event_kind]||'业务记录'}}</text><text>{{dayLabel(event.occurred_at)}} {{clock(event.occurred_at)}}</text></view><text v-if="event.reason_description" class="timeline-reason">{{event.reason_description}}</text><text class="record-meta">{{event.actor_name||'原记录办理主体'}}</text></view></view></view></view><view v-else class="detail-placeholder surface"><AppIcon name="calendar" :size="42" color="#758296"/><text>选择一条预约，查看完整安排与办理历史</text><text>改期、取消及到店操作会依据当前状态开放。</text></view></view></view>
 <view v-if="cancelOpen&&a" class="modal-overlay"><view class="cancel-modal" role="dialog" aria-label="取消预约"><text class="cancel-title">确认取消这次预约？</text><text class="cancel-summary">{{a.clinic_name}} · {{dayLabel(a.starts_at)}} {{clock(a.starts_at)}}</text><text class="cancel-note">原预约及原因会保留。取消本次时段不会自动终止整个治疗计划。</text><text class="label">取消原因</text><textarea class="input" v-model="cancelReason" aria-label="取消原因" placeholder="请说明取消本次安排的原因"/><view v-if="error" class="error">{{error}}</view><view class="cancel-buttons"><button :disabled="busy" @click="cancelOpen=false">保留预约</button><button class="primary" :disabled="busy" @click="cancel">{{busy?'办理中…':'确认取消'}}</button></view></view></view>
 </WorkspaceShell></template>
<style scoped>.followup-entry{margin-bottom:18px}
.appointment-header{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px}.page-title{font-size:26px;font-weight:600;display:block}.page-caption{display:block;color:#758296;font-size:13px;line-height:1.8;margin-top:7px}.new-appointment{display:flex;align-items:center;gap:7px}.appointments-layout{display:grid;grid-template-columns:380px minmax(0,1fr);gap:22px;align-items:start}.surface{background:#fff;border:1px solid #e3e8ef;border-radius:12px;overflow:hidden;box-shadow:0 3px 12px rgba(37,51,71,.04)}.appointment-tabs{display:flex;padding:9px 9px 0;border-bottom:1px solid #e3e8ef;gap:4px}.appointment-tabs button{flex:1;display:flex;justify-content:center;align-items:center;gap:5px;border:0;border-bottom:2px solid transparent;background:transparent;border-radius:0;padding:13px 5px;font-size:13px;white-space:nowrap}.appointment-tabs button.active{color:#3278cf;border-bottom-color:#3278cf;font-weight:600}.appointment-tabs button>text:last-child{font-size:11px;border-radius:4px;background:#f2f5f8;padding:1px 4px}.appointment-search{padding:17px;display:flex;gap:9px;flex-wrap:wrap;border-bottom:1px solid #e3e8ef}.search-input{display:flex;gap:8px;align-items:center;width:100%;border:1px solid #e3e8ef;border-radius:8px;padding:10px}.search-input input{flex:1;min-width:0;font-size:13px;height:23px}.date-filter{font-size:12px;padding:7px 10px;min-height:36px;display:flex;align-items:center;gap:6px}.clear-filter{border:0;background:transparent;color:#758296;min-height:36px;padding:5px;font-size:12px}.appointment-records{padding:0 15px}.appointment-record{width:100%;padding:19px 9px;text-align:left;border:0;border-bottom:1px solid #e3e8ef;border-radius:0;background:transparent}.appointment-record.selected{background:#edf5ff}.record-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.record-date{font-size:13px}.status-tag{display:inline-flex;font-size:11px;line-height:1.6;border-radius:4px;padding:3px 7px;background:#edf5ff;color:#3278cf;white-space:nowrap}.status-tag.warning{color:#9d681a;background:#f2f5f8}.record-time{display:block;font-size:22px;font-weight:600;margin:10px 0}.record-clinic{display:block;font-size:14px;font-weight:500;margin-bottom:5px}.record-meta{display:block;color:#758296;font-size:11px;line-height:1.8}.record-bottom{display:flex;justify-content:space-between;gap:10px;margin-top:15px;color:#758296;font-size:10px}.loaded-caption{display:block;padding:15px;text-align:center;font-size:11px;color:#758296}.load-more{margin:15px;width:calc(100% - 30px);font-size:12px}.appointments-empty{padding:40px 20px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:14px;font-size:13px;color:#758296}.appointments-empty>text:last-child{font-size:11px;line-height:1.8}.appointment-detail{display:flex;flex-direction:column;gap:20px;min-width:0}.back-list{display:none}.detail-card-header{display:flex;justify-content:space-between;align-items:center;padding:18px 24px;border-bottom:1px solid #e3e8ef}.detail-label{font-weight:600;font-size:16px}.detail-main{padding:25px}.detail-clinic{font-size:23px;font-weight:600;display:block}.detail-time{font-size:17px;margin:12px 0;display:block}.detail-address{font-size:12px;color:#758296;line-height:1.8;display:block}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:23px 20px;margin:26px 0;padding:24px 0;border-top:1px solid #e3e8ef;border-bottom:1px solid #e3e8ef}.detail-grid>view>text:first-child,.requested-projects>text:first-child{display:block;font-size:12px;color:#758296;margin-bottom:7px}.detail-grid>view>text:last-child{font-size:15px;font-weight:500}.requested-projects{margin:21px 0;font-size:14px;line-height:1.8}.requested-projects>text{display:block}.detail-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.detail-actions>button{font-size:13px}.detail-actions>.primary{flex:1}.cancel-action{color:#bd4a46}.detail-info,.detail-warning{display:flex;align-items:flex-start;gap:9px;background:#edf5ff;border-radius:8px;padding:15px;font-size:12px;line-height:1.9;margin-top:20px}.detail-warning{color:#9d681a;background:#f2f5f8}.detail-number{display:block;font-size:11px;color:#758296;margin-top:25px;padding-top:20px;border-top:1px solid #e3e8ef;overflow-wrap:anywhere}.invoice-preview{display:flex;align-items:center;flex-wrap:wrap;gap:14px;border-top:1px solid #e3e8ef;margin-top:24px;padding-top:21px;font-size:14px}.invoice-preview>view{flex:1}.invoice-preview>text{font-size:20px;font-weight:600;color:#3278cf}.text-button{padding:3px;background:transparent;border:0;font-size:12px;color:#3278cf;min-height:32px}.detail-caption{font-size:12px;color:#758296;display:block;margin-top:23px;line-height:1.9}.section-title-small{display:block;font-size:16px;font-weight:600;margin-bottom:20px}.continuity-links{padding:23px}.continuity-links>button{display:flex;align-items:center;justify-content:space-between;gap:12px;border:0;border-top:1px solid #e3e8ef;padding:15px 0;text-align:left;background:transparent;border-radius:0;width:100%}.continuity-links>button>view>text:first-child{display:block;font-size:13px;margin-bottom:5px}.continuity-links>button>view>text:last-child{font-size:11px;color:#758296}.appointment-timeline{padding:24px}.timeline-row{display:flex;align-items:flex-start;gap:15px;position:relative;padding-bottom:23px}.timeline-point{height:9px;width:9px;border:2px solid #3278cf;border-radius:50%;margin-top:5px;flex-shrink:0}.timeline-row:after{position:absolute;content:'';left:4px;top:15px;bottom:0;width:1px;background:#e3e8ef}.timeline-row:last-child{padding-bottom:0}.timeline-row:last-child:after{display:none}.timeline-row>view:last-child{flex:1;min-width:0}.timeline-heading{display:flex;justify-content:space-between;gap:12px;font-size:13px}.timeline-heading>text:last-child{font-size:11px;color:#758296}.timeline-reason{display:block;font-size:12px;line-height:1.9;margin:6px 0}.detail-placeholder{min-height:390px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:18px;padding:30px;text-align:center;font-size:14px;color:#758296}.detail-placeholder>text:last-child{font-size:12px;line-height:1.8}.notice-result{padding:13px 16px;background:#edf5ff;color:#253347;border-radius:8px;display:flex;gap:9px;align-items:center;margin-bottom:20px;font-size:13px}.error{margin-bottom:18px}.modal-overlay{position:fixed;inset:0;background:rgba(37,51,71,.32);display:flex;align-items:center;justify-content:center;padding:24px;z-index:50}.cancel-modal{width:100%;max-width:490px;padding:28px;background:#fff;border:1px solid #e3e8ef;border-radius:14px;box-shadow:0 3px 12px rgba(37,51,71,.04)}.cancel-title{font-size:23px;font-weight:600;display:block}.cancel-summary{display:block;margin-top:13px;font-size:14px;line-height:1.8}.cancel-note{display:block;font-size:12px;color:#758296;line-height:1.9;margin:17px 0 22px}.cancel-buttons{display:flex;gap:12px;margin-top:24px}.cancel-buttons>button{flex:1;font-size:14px}.cancel-modal>.error{margin:14px 0 0}@media(max-width:1100px){.appointments-layout{grid-template-columns:330px minmax(0,1fr)}.detail-main{padding:21px}.detail-card-header{padding:17px 21px}.detail-time{font-size:15px}}@media(max-width:800px){.appointments-layout{grid-template-columns:1fr}.detail-placeholder{display:none}.has-selection .appointments-master{display:none}.back-list{display:flex;align-items:center;gap:6px;font-size:13px;border:0;padding:0;min-height:32px;background:transparent;color:#3278cf}.detail-clinic{font-size:21px}.appointment-timeline{padding:21px}.appointment-header{align-items:flex-start}.page-title{font-size:23px}.new-appointment{font-size:12px;padding:9px 12px}.page-caption{font-size:12px}.has-selection .appointment-header{display:none}}@media(max-width:680px){.appointment-header{margin-bottom:20px;gap:12px}.page-title{font-size:21px}.page-caption{font-size:11px;line-height:1.9}.new-appointment{padding:8px 9px;white-space:nowrap;min-height:40px}.appointment-tabs{padding-top:7px}.appointment-tabs button{font-size:12px;padding:13px 3px}.appointment-search{padding:15px}.appointment-records{padding:0 13px}.record-time{font-size:21px}.record-meta{font-size:11px}.detail-main{padding:21px 18px}.detail-card-header{padding:16px 18px}.detail-time{font-size:14px}.detail-grid{gap:21px 16px;margin:22px 0;padding:22px 0}.detail-grid>view>text:last-child{font-size:14px}.detail-actions>button{padding:10px 12px}.detail-actions>.primary{flex-basis:100%}.timeline-heading{flex-direction:column;gap:4px}.appointment-detail{gap:16px}.continuity-links{padding:20px}.cancel-modal{padding:23px 20px}.cancel-title{font-size:21px}.modal-overlay{padding:18px}.cancel-summary{font-size:13px}.cancel-buttons>button{font-size:13px}.cancel-note{font-size:11px}.detail-warning,.detail-info{font-size:11px}.detail-number{font-size:10px}}
.staff-appointment-actions{display:flex;gap:8px;margin-bottom:12px}.staff-appointment-actions>button{margin:0}

.appointment-actions,.queue-toolbar,.queue-links,.lookup-result{display:flex;align-items:center;gap:8px}
.appointment-actions button,.queue-toolbar button{margin:0}
.refresh-appointments,.sort-appointments{display:flex;align-items:center;gap:5px;white-space:nowrap}
.queue-toolbar{width:100%;min-width:0}.queue-toolbar .search-input{flex:1;min-width:0;padding:7px 9px}
.queue-toolbar .quiet{font-size:12px;min-height:38px;padding:5px 9px}
.appointment-tabs button>text:last-child{background:transparent}
.queue-links{justify-content:space-between;width:100%}.queue-links .text-button{margin:0;min-height:34px;font-size:12px}
.lookup-result{justify-content:space-between;width:100%;padding:10px;background:#edf5fc;border-radius:7px;color:#215b90;font-size:13px}
.staff-queue .appointment-header{padding:17px 19px;border:1px solid #dbe6ef;background:#ebf3fa;border-radius:11px;margin-bottom:17px}
.staff-queue .appointments-layout{grid-template-columns:minmax(0,1fr)}
.staff-queue.has-selection .appointments-layout{grid-template-columns:minmax(360px,1.1fr) minmax(300px,1fr)}
.staff-queue .appointment-record,.queue-columns{display:grid;grid-template-columns:1.1fr 1.1fr .9fr .86fr;gap:12px;align-items:center}
.queue-columns{padding:10px 19px;font-size:12px;color:#53687b;background:#f3f7fa;border-bottom:1px solid #e4ebf1}
.staff-queue .appointment-record{padding:13px 5px}
.queue-primary,.queue-secondary{display:block;line-height:1.45;text-align:left}
.queue-primary{font-size:13px;font-weight:660;color:#263d56}
.queue-secondary{font-size:11px;color:#50687c;margin-top:4px;overflow-wrap:anywhere}
.queue-number{font-variant-numeric:tabular-nums}
@media(max-width:1110px){.staff-queue.has-selection .appointments-layout{grid-template-columns:minmax(0,1fr)}}
@media(max-width:680px){.appointment-header,.appointment-actions{flex-wrap:wrap}.staff-queue .appointment-record{grid-template-columns:1fr 1fr}.queue-columns{display:none}.queue-toolbar{flex-wrap:wrap}.queue-toolbar .search-input{flex-basis:calc(100% - 70px)}.staff-queue .appointment-header{padding:12px}.appointments-layout{grid-template-columns:minmax(0,1fr)}}
</style>
