<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import WorkspaceShell from '../../components/WorkspaceShell.vue'
import AppIcon from '../../components/AppIcon.vue'
import { request } from '../../api'
import { clock, dayLabel, goCase, requireWorkspace, type Row } from '../../workspace'

const clinics = ref<Row[]>([])
const chosenId = ref(0)
const selected = computed(() => clinics.value.find(clinic => clinic.id === chosenId.value))
const busy = ref(false)
const error = ref('')
const expanded = ref<number | null>(null)
const interval = ref('')
const doctors = computed(() => selected.value?.doctors || [])
const avatar = (name: string) => name.slice(-2)

async function load() {
  if (!await requireWorkspace('UC02')) return
  busy.value = true
  error.value = ''
  try {
    const directory = await request('/api/clinic-directory')
    clinics.value = directory.clinics
    interval.value = dayLabel(directory.from).split(' 周')[0] + '至' + dayLabel(directory.through).split(' 周')[0]
    if (!selected.value) select(clinics.value.find(c => c.doctors.length)?.id || clinics.value[0]?.id || 0)
  } catch (problem: unknown) {
    error.value = problem instanceof Error ? problem.message : '暂时无法读取门店'
  } finally {
    busy.value = false
  }
}

function select(id: number) {
  chosenId.value = id
  expanded.value = null
}

function book(id: number, day: string, dentist?: number) {
  goCase('UC02', { clinic: id, ...(day ? { day } : {}), ...(dentist ? { dentist } : {}) })
}

function contact(phone: string) { uni.makePhoneCall({phoneNumber:phone}) }

onShow(load)
</script>

<template>
 <WorkspaceShell title="门店与医生" active="UC02" back>
  <view class="directory">
   <view class="directory-intro">
    <text class="directory-title">选择就诊门店</text>
    <text class="directory-note">查看近期出诊，再选择适合你的时间。</text>
   </view>
   <view v-if="error" class="error">{{error}} <button class="text-button" @click="load">重试</button></view>
   <text v-else-if="busy&&!clinics.length" class="directory-note">正在读取门店与出诊安排…</text>
   <view class="clinic-grid" v-if="clinics.length">
    <button v-for="clinic in clinics" :key="clinic.id" class="directory-clinic" :class="{selected:clinic.id===chosenId}" :aria-pressed="clinic.id===chosenId" @click="select(clinic.id)">
     <image class="directory-photo" :src="clinic.photo||'/static/images/clinic-scene.jpg'" mode="aspectFill" aria-label="门店环境示意"/>
     <view class="clinic-title-line"><text>{{clinic.clinic_name}}</text><AppIcon :name="clinic.id===chosenId?'checkbox-filled':'right'" :size="17"/></view>
     <text class="directory-note">{{clinic.doctors.length?clinic.doctors.length+' 位近期出诊':'近期暂无出诊'}}</text>
    </button>
   </view>
   <view v-if="selected" class="selected-clinic">
    <view class="directory-section-heading">
     <view><text class="directory-subtitle">{{selected.clinic_name}}</text><text class="directory-note">{{selected.postal_address}}</text></view>
     <button v-if="selected.phone&&!selected.synthetic" class="quiet clinic-contact" @click="contact(selected.phone)"><AppIcon name="phone" :size="17"/> 联系门店</button>
    </view>
    <view class="team-heading"><text class="directory-subtitle">近期出诊医生</text><text class="directory-note">{{interval}} · 已发布</text></view>
    <text v-if="!doctors.length" class="directory-empty">近期暂无已发布出诊，可选择其他门店。</text>
    <view v-for="doctor in doctors" :key="doctor.id" class="directory-doctor">
     <view class="directory-doctor-main">
      <image v-if="doctor.photo" class="directory-avatar" :src="doctor.photo" mode="aspectFill" aria-label="教学医生肖像"/>
      <view v-else class="directory-avatar directory-placeholder">{{avatar(doctor.full_name)}}</view>
      <view><text class="doctor-title">{{doctor.full_name}}</text><text class="directory-note">{{doctor.introduction}}</text></view>
     </view>
     <view class="doctor-session-row" v-for="(session,index) in (expanded===doctor.id?doctor.sessions:doctor.sessions.slice(0,2))" :key="session.starts_at+'-'+index">
      <text>{{dayLabel(session.work_date)}} {{clock(session.starts_at)}}–{{clock(session.ends_at)}}</text>
      <button class="text-button" @click="book(selected.id,session.work_date,doctor.id)">查号源 <AppIcon name="right" :size="13"/></button>
     </view>
     <button v-if="doctor.sessions.length>2" class="text-button additional-sessions" @click="expanded=expanded===doctor.id?null:doctor.id">{{expanded===doctor.id?'收起':'更多出诊'}}</button>
    </view>
    <text class="directory-note directory-caption">出诊安排以发布记录为准，具体号源在预约时查询。教学医生与门店图片为示意。</text>
   </view>
  </view>
 </WorkspaceShell>
</template>

<style scoped>
.directory{max-width:930px;margin:auto;color:#23334b}
.directory-intro{margin-bottom:17px}
.directory-title,.directory-subtitle,.doctor-title{display:block;font-weight:660}
.directory-title{font-size:25px;line-height:1.25;margin:0 0 6px}
.directory-subtitle{font-size:17px}.doctor-title{font-size:16px;margin-bottom:5px}
.directory-note{display:block;color:#53667a;font-size:12px;line-height:1.6}
.clinic-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:20px}
.directory-clinic{padding:0 0 9px;margin:0;overflow:hidden;text-align:left;min-width:0;background:#fff;border:1px solid #dbe4ee;border-radius:10px}
.directory-clinic.selected{border-color:#3278cf;box-shadow:0 0 0 1px #3278cf}
.directory-photo{display:block;width:100%;height:125px;background:#e8f0f6}
.clinic-title-line{padding:7px 9px 0;display:flex;justify-content:space-between;gap:5px;text-align:left;align-items:center;font-size:13px;font-weight:660}
.directory-clinic .directory-note{text-align:left;padding:2px 9px 0}
.selected-clinic{background:#fff;border:1px solid #dbe4ee;border-radius:12px;padding:17px}
.directory-section-heading,.team-heading,.doctor-session-row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.directory-section-heading{padding-bottom:14px;border-bottom:1px solid #e4ebf1}
.directory-section-heading .directory-note{margin-top:4px}
.clinic-contact{display:flex;align-items:center;gap:4px;flex-shrink:0;font-size:12px;padding:6px;margin:0}
.team-heading{padding:15px 0 2px}
.directory-doctor{padding:16px 0 10px;border-bottom:1px solid #e4ebf1}
.directory-doctor-main{display:flex;align-items:center;gap:11px;margin-bottom:8px}
.directory-avatar{width:62px;height:70px;flex-shrink:0;border-radius:8px;background:#e8f0f6}
.directory-placeholder{display:flex;align-items:center;justify-content:center;color:#35547b;font-size:18px}
.doctor-session-row{padding:4px 0;color:#3e5166;font-size:13px;min-height:41px}
.text-button{border:0;background:transparent;color:#2462a5;padding:4px 0;margin:0;min-height:40px;font-size:13px;display:flex;gap:4px;align-items:center}
.additional-sessions{min-height:38px}
.directory-caption,.directory-empty{display:block;margin-top:17px}
@media(max-width:650px){.directory-title{font-size:22px}.clinic-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.directory-photo{height:84px}.selected-clinic{padding:12px}.doctor-session-row{font-size:12px}}
</style>
