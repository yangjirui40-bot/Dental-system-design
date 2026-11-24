<script setup lang="ts">
import { computed } from 'vue';import type { Field } from '../forms';import { optionLabel } from '../forms';import {localDay,clock} from '../workspace'
import {clientSurface} from '../api'
let staffH5=false
// #ifdef H5
staffH5=clientSurface==='staff'
// #endif
const props=defineProps<{field:Field,modelValue:any,resources:Record<string,any[]>}>();const emit=defineEmits(['update:modelValue'])
const kind=computed(()=>props.field.type||'text');const options=computed(()=>kind.value.startsWith('enum:')?kind.value.slice(5).split(',').map(x=>{const [id,label]=x.split('=');return{id,label}}):(props.resources[kind.value.split(':')[1]]||[]).map(r=>({...r,label:optionLabel(r)})))
const nativeSelection=computed(()=>kind.value.startsWith('select:')||kind.value.startsWith('enum:'))
function nativeSelect(event:Event){
 const value=(event.target as HTMLSelectElement).value
 emit('update:modelValue',options.value.find(option=>String(option.id)===value)?.id??'')
}
function nativeDateTime(event:Event){
 const value=(event.target as HTMLInputElement).value
 emit('update:modelValue',value?value+':00+08:00':'')
}
const selected=computed(()=>options.value.find(x=>String(x.id)===String(props.modelValue))?.label||'请选择')
function input(e:any){emit('update:modelValue',kind.value==='number'?(e.detail.value===''?'':Number(e.detail.value)):e.detail.value)}
function select(e:any){emit('update:modelValue',options.value[Number(e.detail.value)]?.id)}
function boolChange(e:any){emit('update:modelValue',e.detail.value)}
function dt(part:string,value:string){const old=typeof props.modelValue==='string'&&props.modelValue?props.modelValue:new Date().toISOString();const day=part==='date'?value:localDay(old);const at=part==='time'?value:clock(old);emit('update:modelValue',day+'T'+at+':00+08:00')}
function toggle(id:any){const xs=Array.isArray(props.modelValue)?[...props.modelValue]:[];const i=xs.indexOf(id);if(i<0)xs.push(id);else xs.splice(i,1);emit('update:modelValue',xs)}
</script>
<template><view v-if="kind!=='record'" class="field"><text class="label">{{field.label}}<text v-if="field.required" class="danger"> *</text></text>
 <!-- #ifdef H5 -->
 <component v-if="staffH5&&nativeSelection" :is="'select'" class="input staff-control" :aria-label="field.label"
   :value="String(modelValue??'')" @change="nativeSelect">
  <option value="">{{options.length?'请选择':'当前范围暂无可选项'}}</option>
  <option v-for="option in options" :key="option.id" :value="String(option.id)">{{option.label}}</option>
 </component>
 <component v-else-if="staffH5&&(kind==='date'||kind==='datetime')" :is="'input'" class="input staff-control" :aria-label="field.label"
   :type="kind==='date'?'date':'datetime-local'" :value="modelValue?(kind==='date'?modelValue:localDay(modelValue)+'T'+clock(modelValue)):''"
   @change="kind==='datetime'?nativeDateTime($event):emit('update:modelValue',($event.target as HTMLInputElement).value)" />
 <component v-else-if="staffH5&&kind==='boolean'" :is="'input'" type="checkbox" class="staff-checkbox"
   :aria-label="field.label" :checked="!!modelValue" @change="emit('update:modelValue',($event.target as HTMLInputElement).checked)"/>
 <template v-else>
 <!-- #endif -->
 <switch v-if="kind==='boolean'"  :aria-label="field.label" :checked="!!modelValue" color="#3278cf" @change="boolChange"/>
 <picker v-else-if="kind.startsWith('select:')||kind.startsWith('enum:')" :range="options" range-key="label" :aria-label="field.label" @change="select"><view class="input">{{selected}}<text class="muted" style="float:right">⌄</text></view></picker>
 <view v-else-if="kind.startsWith('multi:')" class="multi"><button v-for="o in options" :key="o.id" :class="{'chosen':(modelValue||[]).includes(o.id)}" @click="toggle(o.id)">{{o.label}}</button><text v-if="!options.length" class="muted small">暂无可选记录</text></view>
 <picker v-else-if="kind==='date'" mode="date" :value="modelValue||''" @change="emit('update:modelValue',$event.detail.value)"><view class="input">{{modelValue||'选择日期'}}</view></picker>
 <view v-else-if="kind==='datetime'" class="row"><picker mode="date" @change="dt('date',$event.detail.value)"><view class="input">{{modelValue?localDay(modelValue):'选择日期'}}</view></picker><picker mode="time" @change="dt('time',$event.detail.value)"><view class="input">{{modelValue?clock(modelValue):'选择时间'}}</view></picker></view>
 <textarea v-else-if="kind==='textarea'" class="input" :aria-label="field.label" :value="modelValue||''" @input="input"/>
 <input v-else class="input" :aria-label="field.label" :password="kind==='password'" :type="kind==='number'?'digit':'text'" :value="modelValue??''" @input="input"/>
 <!-- #ifdef H5 -->
 </template>
 <!-- #endif -->
 </view></template>
<style scoped>.multi{display:flex;gap:8px;flex-wrap:wrap}.multi button{font-size:13px;padding:6px 10px}.chosen{background:#edf5ff;border-color:#3278cf;color:#3278cf}.row picker{flex:1;min-width:0}.staff-control{width:100%;font-family:inherit;color:inherit}.staff-checkbox{width:20px;height:20px;accent-color:#3278cf}</style>
