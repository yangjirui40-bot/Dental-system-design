<script setup lang="ts">
import {ref,computed} from 'vue'
import {onShow} from '@dcloudio/uni-app'
import WorkspaceShell from '../../components/WorkspaceShell.vue'
import AppIcon from '../../components/AppIcon.vue'
import {work,personal,sections,caseIcons,caseHints,caseLabel,goCase,requireWorkspace,canUse} from '../../workspace'
type Entry={code:string;name:string;hint:string;aliases?:string;params?:Record<string,string>}
const query=ref('')
onShow(()=>requireWorkspace())
const patientGroups:{name:string;items:Entry[]}[]=[
 {name:'预约与到店',items:[{code:'UC02',name:'预约医生',hint:'看医生简介，选择门店和可约时间',aliases:'挂号照片医生'},{code:'UC03',name:'我的预约',hint:'查看安排、改期或取消，保留原约历史',aliases:'排期改约取消'},{code:'UC04',name:'到店报到',hint:'已经到达门店，登记当日到店情况',params:{action:'arrive'}}]},
 {name:'治疗与费用',items:[{code:'UC14',name:'治疗计划',hint:'查看阶段进度、前序条件和下一次安排',aliases:'疗程接续复诊',params:{dataset:'phases'}},{code:'UC14',name:'费用账单',hint:'按日期查有效结算，查看实际收费明细',aliases:'结算账单收费',params:{dataset:'invoices'}}]},
 {name:'我的资料',items:[{code:'UC01',name:'个人资料与记录',hint:'基本信息、紧急联系人、过敏及修订记录',aliases:'档案历史'},{code:'UC01',name:'修改基本资料',hint:'更新联系方式、账单地址和紧急联系人',params:{action:'save'}},{code:'UC01',name:'新增联系人',hint:'分别登记紧急联系、监护或代办用途',params:{action:'contact'}},{code:'UC01',name:'申报过敏',hint:'逐项说明过敏物质与反应，保留原申报',params:{action:'allergy'}}]}
]
const groups=computed(()=>{
 const source=personal.value?patientGroups:sections.map(s=>({name:s.name,items:(work.data?.menu||[]).filter(i=>s.codes.includes(i.code)).map(i=>({code:i.code,name:caseLabel(i.code,i.name),hint:caseHints[i.code]} as Entry))}))
 const text=query.value.trim().toLowerCase()
 return source.map(group=>({...group,items:group.items.filter(item=>canUse(item.code)&&(!text||(item.name+item.hint+(item.aliases||'')).toLowerCase().includes(text)))})).filter(g=>g.items.length)
})
</script>
<template><WorkspaceShell title="服务导航" active="services" back><view class="page-heading"><view><text class="page-title">你要办理什么？</text><text class="page-description">{{personal?'预约、费用和个人资料都在这里。':'按当前岗位查找业务，常用操作可直接进入。'}}</text></view></view><view class="service-search"><AppIcon name="search" :size="20" color="#758296"/><input v-model="query" :placeholder="personal?'搜索医生、改期、账单、联系人…':'搜索排班、诊疗、费用、账号…'" aria-label="查找服务"/><button v-if="query" class="text-button" @click="query=''">清除</button></view><view v-for="group in groups" :key="group.name" class="service-group"><text class="group-title">{{group.name}}</text><view class="service-list"><button v-for="item in group.items" :key="item.code+item.name" class="service-line" @click="goCase(item.code,item.params||{})"><AppIcon :name="caseIcons[item.code]" :size="23"/><view><text class="service-name">{{item.name}}</text><text class="caption">{{item.hint}}</text></view><AppIcon name="right" :size="16" color="#758296"/></button></view></view><view v-if="!groups.length" class="empty-state"><text>没有找到对应服务</text><text>可以试试“预约”“费用”“联系人”，或清除搜索查看全部入口。</text><button class="text-button" @click="query=''">查看全部服务</button></view></WorkspaceShell></template>
<style scoped>.service-search{display:flex;align-items:center;gap:12px;max-width:640px;background:#fff;border:1px solid #e3e8ef;border-radius:9px;padding:13px 16px;margin-bottom:28px}.service-search>input{flex:1;min-width:0;font-size:14px}.service-group{margin:24px 0 30px;max-width:900px}.group-title{font-size:17px;font-weight:600;display:block;margin-bottom:13px}.service-list{background:#fff;border:1px solid #e3e8ef;border-radius:10px;padding:0 20px}.service-line{display:flex;align-items:center;gap:16px;width:100%;padding:20px 0;text-align:left;border:0;border-bottom:1px solid #e3e8ef;border-radius:0;background:transparent}.service-line:last-child{border-bottom:0}.service-line>view{flex:1;min-width:0}.service-name{font-size:16px;font-weight:500;display:block;margin-bottom:5px}@media(max-width:680px){.service-list{padding:0 16px}.service-line{gap:13px;padding:18px 0}.service-name{font-size:15px}.service-search{padding:11px 13px}.service-search>input{font-size:13px}.group-title{font-size:16px}}
</style>
