<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '../../components/AppIcon.vue'
import { format, request } from '../../api'
import { clock, dayLabel, localDay, resources, work, type Row } from '../../workspace'

const props = defineProps<{ mode: 'week'|'roster', revision: number; initialClinic?: number; initialCross?: boolean }>()
const emit = defineEmits<{ (event:'inspect'|'clinic',id:number):void }>()
function addDays(day: string, count: number) {
  const stamp = new Date(day + 'T12:00:00Z')
  stamp.setUTCDate(stamp.getUTCDate() + count)
  return stamp.toISOString().slice(0,10)
}
function currentWeek() {
  const day = localDay()
  return addDays(day,-((new Date(day+'T12:00:00Z').getUTCDay()+6)%7))
}
const start = ref(currentWeek())
const dateOptions = computed(() => Array.from({length:7},(_, i) => addDays(start.value, i)))
const clinic = ref(props.initialClinic||0)
const query = ref('')
const onlyPublished = ref(true)
const crossOnly=ref(!!props.initialCross)
const data = ref<Row>({doctors:[],duties:[]})
const busy = ref(false)
const error = ref('')
const clinics = computed(() => resources.value.clinics || [])
const group = computed(() => work.data?.scope.scope_kind==='group')
const records = computed<Row[]>(() => data.value.duties.filter((d:Row)=>!onlyPublished.value||d.publication_state==='published'))
const crossClinic = computed(() => {
 const locations=new Map<number,Set<number>>()
 for(const duty of records.value){
  if(!locations.has(duty.dentist_id))locations.set(duty.dentist_id,new Set())
  locations.get(duty.dentist_id)!.add(duty.clinic_id)
 }
 return locations
})
const scopeName = computed(()=>work.data?.scope.clinic_name||clinics.value[0]?.clinic_name||'当前授权门店')
const people = computed<Row[]>(() => data.value.doctors.filter((d:Row) => {
 const term = query.value.trim().toLowerCase()
 const matches=!term||[d.full_name,d.employee_no,d.professional_no].some(value=>String(value||'').toLowerCase().includes(term))
 return matches&&(!crossOnly.value||clinic.value||(crossClinic.value.get(d.id)?.size||0)>1)
}))
const dutyIndex = computed(() => {
 const index = new Map<string,Row[]>()
 for (const duty of records.value) {
  for (const day of dateOptions.value) {
   if (localDay(duty.starts_at)>day||Date.parse(duty.ends_at)<=Date.parse(day+'T00:00:00+08:00')) continue
   const key=duty.dentist_id+'-'+day
   const shifts=index.get(key)||[]
   shifts.push(duty)
   index.set(key,shifts)
  }
 }
 return index
})
function onDay(id:number,day:string) {return dutyIndex.value.get(id+'-'+day)||[]}
function times(duty:Row,day:string) {
 return (localDay(duty.starts_at)<day?'00:00':clock(duty.starts_at))+'–'+(localDay(duty.ends_at)>day?'24:00':clock(duty.ends_at))
}
function weekDuties(id:number) {return records.value.filter(d=>d.dentist_id===id)}
let latest = 0
async function reload() {
 const requestId=++latest
 error.value=''
 busy.value=true
 data.value={doctors:[],duties:[]}
 try {
  const answer=await request('/api/duties/calendar?start='+start.value+(clinic.value?'&clinic_id='+clinic.value:''))
  if(requestId===latest)data.value=answer
 } catch (problem:unknown) {
  if(requestId===latest)error.value=problem instanceof Error?problem.message:'暂时无法查询出诊'
 } finally {if(requestId===latest)busy.value=false}
}
watch(clinic,id=>emit('clinic',id))
watch([start,clinic,()=>props.revision],reload,{immediate:true})
</script>
<template>
 <view class="calendar-shell">
  <view class="calendar-controls">
   <view class="week-controls" aria-label="周范围">
    <button class="calendar-icon" aria-label="上一周" @click="start=addDays(start,-7)"><AppIcon name="left" :size="17"/></button>
    <text class="week-label">{{dayLabel(start).split(' 周')[0]}} – {{dayLabel(dateOptions[6]).split(' 周')[0]}}</text>
    <button class="calendar-icon" aria-label="下一周" @click="start=addDays(start,7)"><AppIcon name="right" :size="17"/></button>
    <button class="quiet back-now" @click="start=currentWeek()">本周</button>
   </view>
   <view class="calendar-filters">
    <label v-if="group" class="select-wrap"><text>门店</text><select v-model.number="clinic" aria-label="按门店查看出诊"><option :value="0">全部</option><option v-for="branch in clinics" :key="branch.id" :value="branch.id">{{branch.clinic_name}}</option></select></label>
    <text v-else class="person-meta">{{scopeName}}</text><input class="input doctor-search" aria-label="搜索医生" placeholder="搜索姓名或编号" v-model="query"/>
    <button v-if="group&&!clinic" class="quiet cross-filter" :class="{chosen:crossOnly}" :aria-pressed="crossOnly" @click="crossOnly=!crossOnly">仅跨店出诊</button><button class="quiet toggle-state" @click="onlyPublished=!onlyPublished" :aria-pressed="!onlyPublished">{{onlyPublished?'仅已发布':'包含未发布'}}</button>
   </view>
  </view>
  <view class="calendar-meta"><text>{{busy?'正在取数…':people.length+' 位医生 · '+records.filter(d=>people.some(p=>p.id===d.dentist_id)).length+' 段出诊'}}</text><text>点击出诊查看详情与调整入口</text></view>
  <view v-if="error" class="error">{{error}} <button class="quiet" @click="reload">重试</button></view>
  <view v-else-if="!busy&&!people.length" class="calendar-empty">{{crossOnly?'本周暂无符合条件的跨店出诊。可换一周查看。':'没有匹配的医生。'}}</view>
  <view v-else-if="mode==='week'&&people.length" class="calendar-scroll" tabindex="0" aria-label="医生周排班，可横向浏览">
   <table class="doctor-calendar">
    <thead><tr><th scope="col">接诊医生</th><th v-for="day in dateOptions" :key="day" scope="col" :class="{'current-day':day===localDay()}">{{dayLabel(day)}}</th></tr></thead>
    <tbody>
     <tr v-for="doctor in people" :key="doctor.id">
      <th scope="row"><view class="doctor-line"><image v-if="doctor.photo" :src="doctor.photo" mode="aspectFill" class="calendar-avatar" aria-label="教学肖像"/><view v-else class="calendar-avatar avatar-letter">{{doctor.full_name.slice(-2)}}</view><view><text class="person-name">{{doctor.full_name}}</text><text class="person-meta">{{doctor.employee_no}}</text><text v-if="(crossClinic.get(doctor.id)?.size||0)>1" class="cross-tag">跨店出诊</text></view></view></th>
      <td v-for="day in dateOptions" :key="day" :class="{'current-day':day===localDay()}">
       <button v-for="duty in onDay(doctor.id,day)" :key="duty.id" class="calendar-duty" :class="{'draft-duty':duty.publication_state!=='published'}" @click="emit('inspect',duty.id)">
        <text>{{times(duty,day)}}</text><text>{{duty.clinic_name}}</text><text v-if="duty.publication_state!=='published'">{{format(duty.publication_state)}}</text>
       </button>
       <text v-if="!onDay(doctor.id,day).length" class="calendar-dash">—</text>
      </td>
     </tr>
    </tbody>
   </table>
  </view>
  <view v-else-if="people.length" class="roster">
   <view v-for="doctor in people" :key="doctor.id" class="roster-card">
    <view class="doctor-line"><image v-if="doctor.photo" :src="doctor.photo" mode="aspectFill" class="roster-avatar" aria-label="教学肖像"/><view v-else class="roster-avatar avatar-letter">{{doctor.full_name.slice(-2)}}</view><view><text class="person-name">{{doctor.full_name}}</text><text class="person-meta">{{doctor.employee_no}} · {{weekDuties(doctor.id).length}} 段出诊</text><text v-if="doctor.employed_to" class="person-meta">任职截至 {{doctor.employed_to}}</text><text v-if="(crossClinic.get(doctor.id)?.size||0)>1" class="cross-tag">跨店出诊</text></view></view>
    <text v-if="doctor.synthetic_profile" class="roster-intro">{{doctor.introduction}} <text class="person-meta">教学档案</text></text>
    <button v-for="duty in weekDuties(doctor.id)" :key="duty.id" class="roster-duty" @click="emit('inspect',duty.id)"><view><text>{{dayLabel(duty.starts_at)}} {{clock(duty.starts_at)}}–{{clock(duty.ends_at)}}</text><text class="person-meta">{{duty.clinic_name}} · {{format(duty.publication_state)}}</text></view><AppIcon name="right" :size="15"/></button>
    <text v-if="!weekDuties(doctor.id).length" class="person-meta roster-intro">此周暂无所选范围内的出诊。</text>
   </view>
  </view>
 </view>
</template>
<style scoped>
.calendar-shell{background:#fff;border:1px solid #dbe5ed;border-radius:12px;overflow:hidden;min-width:0}
.calendar-controls{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:13px;padding:14px 16px}
.calendar-filters,.week-controls,.select-wrap,.doctor-line{display:flex;align-items:center;gap:8px}
.week-label{font-size:15px;font-weight:660;min-width:123px;text-align:center}
.calendar-icon,.back-now,.toggle-state,.cross-filter{margin:0;min-height:38px;font-size:13px}
.cross-filter.chosen{border-color:#4c85bc;background:#e7f2fc;color:#205489}.calendar-icon{min-width:40px;display:flex;align-items:center;justify-content:center;padding:0}
.select-wrap{white-space:nowrap;font-size:13px;color:#4f657a}
.select-wrap select{max-width:180px;min-height:38px;border:1px solid #dbe5ed;border-radius:7px;background:#fff;color:#253347;font:inherit;padding:5px 8px}
.doctor-search{width:150px;min-height:38px;font-size:13px}
.calendar-meta{padding:0 16px 13px;display:flex;justify-content:space-between;gap:10px;color:#53687b;font-size:12px}
.calendar-scroll{overflow-x:auto;max-width:100%}.calendar-empty{padding:30px 16px;color:#53687b}
.doctor-calendar{width:100%;min-width:880px;table-layout:fixed;border-collapse:separate;border-spacing:0;font-size:12px}
.doctor-calendar th,.doctor-calendar td{border-top:1px solid #e4ebf1;border-right:1px solid #e4ebf1;padding:8px 7px;text-align:left;vertical-align:top}
.doctor-calendar thead th{padding:12px 8px;background:#f4f7fa;color:#42607b;text-align:center;font-weight:620}
.doctor-calendar th:first-child{width:139px;position:sticky;left:0;z-index:2;background:#fff;padding:10px}
.doctor-calendar thead th:first-child{background:#f4f7fa;text-align:left}
.doctor-calendar th:last-child,.doctor-calendar td:last-child{border-right:0}
.doctor-calendar td.current-day,.doctor-calendar th.current-day{background:#eef6fd}
.calendar-avatar{width:33px;height:36px;flex-shrink:0;border-radius:6px}
.avatar-letter{display:flex;align-items:center;justify-content:center;background:#e9f1f7;color:#456487;font-weight:600}
.person-name,.person-meta,.calendar-duty text{display:block}
.person-name{font-size:14px;font-weight:660}
.person-meta{font-size:11px;color:#526a80;line-height:1.55;margin-top:3px;overflow-wrap:anywhere}
.cross-tag{display:inline-block;color:#215c8e;background:#e6f1fa;border-radius:4px;padding:2px 4px;font-size:10px;margin-top:3px}.calendar-duty{display:block;text-align:left;width:100%;padding:6px 5px;color:#244a72;font-size:11px;line-height:1.45;margin:0 0 5px;background:#e9f3fd;border:0;border-left:3px solid #3278cf;border-radius:4px;overflow-wrap:anywhere}
.calendar-duty text:first-child{font-weight:650}.calendar-duty.draft-duty{background:#f6efe2;color:#785518;border-left-color:#af7b32}
.calendar-dash{display:block;text-align:center;color:#8294a5;padding-top:5px}
.roster{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;background:#f4f7fa;border-top:1px solid #e4ebf1;padding:15px;align-items:start}
.roster-card{min-width:0;padding:13px;background:#fff;border:1px solid #dbe5ed;border-radius:9px}
.roster-avatar{width:48px;height:53px;flex-shrink:0;border-radius:7px}.roster-intro{display:block;margin:10px 0;color:#526a80;font-size:12px;line-height:1.55}
.roster-duty{width:100%;display:flex;text-align:left;align-items:center;justify-content:space-between;gap:5px;border:0;border-top:1px solid #e4ebf1;border-radius:0;background:transparent;margin:0;padding:7px 0;font-size:12px}
@media(max-width:1120px){.roster{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:670px){.calendar-filters{flex-wrap:wrap}.roster{grid-template-columns:minmax(0,1fr)}.calendar-controls{padding:12px}.calendar-meta{flex-wrap:wrap}}
</style>
