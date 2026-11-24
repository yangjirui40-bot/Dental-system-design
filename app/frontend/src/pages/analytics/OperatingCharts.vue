<script setup lang="ts">
import { computed } from 'vue'
import { money, type Row } from '../../workspace'
const props=defineProps<{ report: Row; finance?:boolean; canFilter?:boolean }>()
const emit=defineEmits<{(event:'filter',id:number):void}>()
const series=[
 {key:'seen_count',name:'已接诊'},
 {key:'patient_cancellations',name:'患者取消'},
 {key:'verified_no_shows',name:'核实未到'},
 {key:'unverified_count',name:'待核实'},
 {key:'other_count',name:'其他结果'},
]
const months=computed<Row[]>(()=>props.report.operations?.appointments?.months||[])
const maxCount=computed(()=>Math.max(1,...months.value.map(row=>Number(row.sample_count))))
const result=computed(()=>props.report.operations?.appointments)
const branches=computed(()=>{
 const totals=new Map<number,{ id:number; name:string; revenue:number; expenses:number; profit:number }>()
 for(const row of props.report.rows||[]){
  if(!totals.has(row.clinic_id))totals.set(row.clinic_id,{id:row.clinic_id,name:row.clinic_name,revenue:0,expenses:0,profit:0})
  const total=totals.get(row.clinic_id)!
  total.revenue+=Number(row.revenue||0)
  total.expenses+=Number(row.supplies_cost||0)+Number(row.operating_expense||0)
  total.profit+=Number(row.net_profit||0)
 }
 return [...totals.values()].sort((a,b)=>b.revenue-a.revenue||a.name.localeCompare(b.name,'zh-CN'))
})
const maxMoney=computed(()=>Math.max(1,...branches.value.flatMap(b=>[b.revenue,b.expenses])))
const size=(value:number,max:number)=>Math.max(0,Number(value||0))*100/max+'%'
</script>
<template>
 <view v-if="!finance&&months.length" class="operating-overview">
  <view class="chart-panel" aria-label="各月到期预约结果">
   <view class="chart-header"><view><text class="chart-title">就诊结果按月分布</text><text class="chart-caption">按原预约日期归月 · 单位为人次</text></view><text class="chart-unit">{{result.sample_count}} 条纳入统计</text></view>
   <view class="chart-legend"><text v-for="item in series" :key="item.key"><i :class="item.key"/>{{item.name}}</text></view>
   <view class="month-axes">
    <view v-for="month in months" :key="month.month" class="chart-month">
     <text class="month-name">{{Number(month.month.slice(-2))}} 月</text>
     <view class="chart-track" role="img" :aria-label="series.map(metric=>metric.name+' '+month[metric.key]).join('，')">
      <view v-for="metric in series" :key="metric.key" :class="metric.key" :style="{width:size(month[metric.key],maxCount)}" :title="metric.name+' '+month[metric.key]"/>
     </view>
     <text class="month-count">{{month.sample_count}}</text>
    </view>
   </view>
   <text class="chart-caption chart-footer">改期旧约及机构原因按设计口径单列。未核实的结果保留为待核实。</text>
  </view>
  <view class="chart-panel attention-chart">
   <text class="chart-title">本季需关注</text>
   <view class="attention-row"><text>到期结果待核实</text><text>{{result.unverified_count}}</text></view>
   <view class="attention-row"><text>机构原因安排</text><text>{{result.institutions}}</text></view>
   <view class="attention-row"><text>漏跟进阶段</text><text>{{report.operations.continuity.missing_count}}</text></view>
   <view class="attention-row"><text>未来需求待协调</text><text>{{report.operations.skills.unmet_count}}</text></view>
  </view>
 </view>
 <view v-else-if="finance&&branches.length" class="chart-panel branch-chart">
  <view class="chart-header"><view><text class="chart-title">门店收入与已复核费用</text><text class="chart-caption">当前选定财务版本 · 人民币元</text></view><view class="chart-legend"><text><i class="seen_count"/>结算收入</text><text><i class="cost"/>已复核费用</text></view></view>
  <view class="branch-row" v-for="branch in branches" :key="branch.id">
   <button v-if="canFilter" class="branch-filter" @click="emit('filter',branch.id)">{{branch.name}}</button><text v-else class="month-name">{{branch.name}}</text>
   <view class="branch-bars">
    <view class="branch-bar"><view class="chart-track"><view class="seen_count" :style="{width:size(branch.revenue,maxMoney)}"/></view><text>¥{{money(branch.revenue)}}</text></view>
    <view class="branch-bar"><view class="chart-track"><view class="cost" :style="{width:size(branch.expenses,maxMoney)}"/></view><text>¥{{money(branch.expenses)}}</text></view>
   </view>
   <text class="branch-profit" :class="{loss:branch.profit<0}">净额 ¥{{money(branch.profit)}}</text>
  </view>
  <text class="chart-caption chart-footer">结算收入沿用签署与结算口径。存在待补费用时，以本页的核对清单为准。</text>
 </view>
</template>
<style scoped>
.operating-overview{display:grid;grid-template-columns:minmax(0,2.2fr) minmax(200px,1fr);gap:15px;margin:6px 0 22px}
.chart-panel{min-width:0;background:#fff;border:1px solid #dbe5ed;border-radius:12px;padding:18px;color:#213852}
.chart-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}
.chart-title{display:block;font-size:17px;font-weight:680}
.chart-caption{display:block;color:#52687b;font-size:12px;line-height:1.6;margin-top:4px}
.chart-unit{font-size:12px;color:#24629f;background:#edf5ff;border-radius:6px;padding:5px 8px}
.chart-legend{display:flex;flex-wrap:wrap;gap:7px 15px;margin:14px 0 10px}
.chart-legend text{display:inline-flex;gap:5px;align-items:center;font-size:12px;color:#435b70}
.chart-legend i{width:9px;height:9px;border-radius:2px;display:inline-block}
.month-axes{display:grid;gap:12px;margin-top:19px}
.chart-month{display:grid;grid-template-columns:43px minmax(0,1fr) 24px;align-items:center;gap:8px}
.month-name,.month-count{font-size:13px;font-weight:620}.month-count{text-align:right;font-variant-numeric:tabular-nums}
.chart-track{height:16px;display:flex;border-radius:4px;overflow:hidden;background:#f0f4f8;min-width:0}
.seen_count{background:#3278cf}.patient_cancellations{background:#7da5c7}.verified_no_shows{background:#aa7339}.unverified_count{background:#636e88}.other_count{background:#8b9ba7}.cost{background:#7197ab}
.chart-footer{border-top:1px solid #e4ebf1;padding-top:11px;margin-top:15px}
.attention-chart .chart-title{padding-bottom:9px}
.attention-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 0;border-bottom:1px solid #e4ebf1;font-size:13px}
.attention-row:last-child{border:0}.attention-row text:last-child{font-weight:700;color:#2c67a4}
.branch-chart{margin:17px 0}
.branch-row{display:grid;grid-template-columns:minmax(105px,20%) minmax(0,1fr) minmax(115px,20%);gap:14px;align-items:center;padding:12px 0;border-top:1px solid #e4ebf1}
.branch-filter{padding:4px 0;border:0;background:transparent;color:#2462a5;font-size:13px;font-weight:650;text-align:left;margin:0}.branch-bars{display:grid;gap:5px}
.branch-bar{display:grid;grid-template-columns:minmax(0,1fr) 105px;align-items:center;gap:8px;color:#435b70;font-size:12px}
.branch-bar .chart-track{height:8px}
.branch-profit{text-align:right;font-size:13px;font-weight:650}.branch-profit.loss{color:#865821}
@media(max-width:900px){.operating-overview{grid-template-columns:minmax(0,1fr)}}
@media(max-width:540px){.chart-panel{padding:13px}.branch-row{grid-template-columns:minmax(0,1fr) auto;gap:7px}.branch-bars{grid-column:1/-1;grid-row:2}.branch-bar{grid-template-columns:minmax(0,1fr) 78px}}
</style>
