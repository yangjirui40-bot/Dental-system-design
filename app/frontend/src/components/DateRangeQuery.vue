<script setup lang="ts">
import {localDay} from '../workspace'
defineProps<{from:string,to:string,busy:boolean,label:string}>()
const emit=defineEmits(['update:from','update:to','query','clear'])
</script>
<template><view class="range-query"><text class="range-label">{{label}}（北京时间，含起止日期）</text><view class="range-controls"><picker mode="date" :value="from||localDay()" :aria-label="label+'开始日期'" @change="emit('update:from',$event.detail.value)"><view class="range-date">{{from||'开始日期'}}</view></picker><text>至</text><picker mode="date" :value="to||localDay()" :aria-label="label+'结束日期'" @change="emit('update:to',$event.detail.value)"><view class="range-date">{{to||'结束日期'}}</view></picker><button class="primary" :disabled="busy" @click="emit('query')">{{busy?'查询中…':'查询'}}</button><button :disabled="busy" @click="emit('clear')">重置</button></view></view></template>
<style scoped>.range-query{width:100%;font-size:12px}.range-label{display:block;color:#758296;font-size:11px;line-height:1.8;margin-bottom:9px}.range-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.range-controls picker{flex:1;min-width:95px}.range-date{border:1px solid #e3e8ef;border-radius:7px;padding:9px 10px;background:#fff;min-height:38px}.range-controls>button{font-size:12px;padding:8px 12px;min-height:38px}.range-controls>text{color:#758296}</style>
