import type {Row} from './workspace'
import {clock,dayLabel,clinicName,doctorName,money} from './workspace'
import {format} from './api'
export const pageCopy:Record<string,{title:string;intro:string;rule:string}>={
 UC01:{title:'患者资料',intro:'同一患者身份，接续每一次门店服务。',rule:'联系人与代办权限分开记录；过敏申报与牙医核实分别留痕。'},
 UC04:{title:'到店与接诊',intro:'从实际到店，到负责牙医确认接诊。',rule:'报到仅更新候诊状态；未到、到店未诊及机构原因不可履行分别记录。'},
 UC05:{title:'诊疗记录',intro:'记录检查、患者同意与真正实施的治疗。',rule:'签署前可保存草稿；签署后保留更正链，并自动接续规则内结算。'},
 UC06:{title:'费用结算',intro:'每项费用，都能追溯到已签署的实际治疗。',rule:'保留唯一有效结算版本；非标准价格需独立批准，补开不会重复计费。'},
 UC07:{title:'门店与责任',intro:'维护诊所资料，明确主管任职期间。',rule:'停用保留历史归属；跨店协作沿用统一患者与职员身份。'},
 UC08:{title:'职员与专业资格',intro:'一份人员身份，支持多项资格和跨店出诊。',rule:'资格有效期、真实性核实和撤销状态共同影响可发布出诊。'},
 UC09:{title:'出诊与跨店协调',intro:'把营业日历、资质与跨店转场安排在一起。',rule:'普通替班须覆盖原安排；停诊保留原约并建立患者接续责任。'},
 UC10:{title:'治疗项目与标准',intro:'明确项目名称、计量方式、价格与预计时长。',rule:'草案与批准分开；新标准保留历史版本，编制与批准由不同职责办理。'},
 UC11:{title:'费用归属与复核',intro:'从原始凭据到牙医、门店及季度，逐笔核对。',rule:'分摊合计须等于来源金额；编制与复核分离，缺报不能按零成本处理。'},
 UC12:{title:'季度经营分析',intro:'核对业务来源后，再确认季度经营结果。',rule:'先汇总集团净利润，正向合计再提取10%基金；正式确认固化来源版本。'},
 UC13:{title:'阶段治疗方案',intro:'每个阶段有先决条件，也有明确的承接责任。',rule:'稳定阶段身份贯穿方案修订；先决阶段完成且临床放行后才能预约。'},
 UC14:{title:'预约与结算查询',intro:'查看授权范围内的服务安排和有效结算。',rule:'当前安排、阶段进度及费用来源分别呈现。'},
 UC15:{title:'营业与诊疗资源',intro:'先确认营业，再发布出诊与开放完整时段。',rule:'营业日历与诊疗位状态共同参与预约校验；维护不覆盖历史安排。'},
 UC16:{title:'账号与岗位权限',intro:'让每项办理，都能对应到真实主体及服务范围。',rule:'独立账号按岗位与门店授权；患者代办另需有效的具体事项授权。'},
 UC17:{title:'业务操作记录',intro:'按实际主体、发生时点及业务记录追溯办理。',rule:'查询遵循岗位和门店范围；敏感业务更正保留原有记录。'}
}
export const columnTitles:Record<string,string[]>={
 patients:['患者姓名','档案编号','联系电话','资料状态'],contacts:['联系人','与患者关系','联系电话','联系用途'],authorities:['授权记录','权限事项','有效期间','状态'],
 appointments:['就诊患者','门店与牙医','完整时段','办理状态'],encounters:['实际就诊','患者','门店','接诊状态'],invoices:['结算编号','门店 / 患者','有效费用','版本'],
 clinics:['门店名称','地址','联系电话','营业情况'],employees:['职员姓名','联系电话','任职期间','身份'],dentists:['牙医姓名','执业编号','人员身份','状态'],qualifications:['专业资格','证照编号','有效期间','核实情况'],
 duties:['接诊安排','完整出诊时段','门店','发布情况'],catalog:['治疗项目','项目代码','目录编号','可用情况'],standards:['治疗标准','单位价格','预计时长','标准版本'],standard_drafts:['待批准标准','单位价格','预计时长','审批状态'],
 phases:['治疗阶段','所属计划','承接门店','阶段状态'],followups:['接续事项','负责门店','下次联系期限','办理进展'],calendars:['营业日期','营业时段','门店','开放情况'],operatories:['诊疗资源','资源代码','门店','资源状态'],
 cost_sources:['原始凭据','费用类别','凭据日期','来源行号'],cost_revisions:['来源版本','来源金额','修订依据','状态'],allocations:['归属牙医 / 门店','分摊金额','归属依据','复核情况'],submissions:['齐备声明','牙医 / 门店','报送时点','复核情况'],reports:['季度报告','季度','报告版本','确认情况'],accounts:['账号姓名','登录名称','主体类型','账号状态'],scopes:['岗位授权','数据范围','门店 / 患者','有效状态']
}
const value=(v:any)=>v===null||v===undefined||v===''?'—':String(v)
export function cells(dataset:string,r:Row):string[]{
 const status=format(r.resolution||r.progress_outcome||r.publication_state||r.approval_state||r.review_state||r.confirmation_state||r.resource_state||r.verification_result||'')
 const range=(start:any,end:any)=>start?dayLabel(start)+' '+clock(start)+'—'+clock(end):'—'
 const period=(start:any,end:any)=>value(start)+' 至 '+(end||'持续有效')
 const result:Record<string,any[]>={
 patients:[r.full_name,r.account_no,r.phone,'资料版本 '+r.row_version],contacts:[r.full_name,r.relationship,r.phone,format(r.contact_purpose)],authorities:['授权 '+r.id,format(r.permission_scope),period(r.valid_from?.slice(0,10),r.valid_to?.slice(0,10)),r.revoked_at?'已撤销':'已登记'],
 appointments:[r.patient_name,r.clinic_name+' · '+r.dentist_name,range(r.starts_at,r.ends_at),status],encounters:[r.encounter_no,r.patient_name,clinicName(r.clinic_id),'已确认实际接诊'],invoices:[r.invoice_no,r.clinic_name+(r.patient_name?' · '+r.patient_name:''),'¥'+money(r.total_amount),'有效版本 '+r.revision_no],
 clinics:[r.clinic_name,r.postal_address,r.phone,r.closed_on?'截止 '+r.closed_on:'营业中'],employees:[r.full_name,r.phone,period(r.employed_from,r.employed_to),'职员 '+r.id],dentists:[r.full_name,r.professional_no,'统一职员身份 '+r.id,'已登记'],qualifications:[r.label,r.certificate_no,period(r.valid_from,r.valid_to),r.revoked_at?'已撤销':status],duties:[r.label,range(r.starts_at,r.ends_at),clinicName(r.clinic_id),status],
 catalog:[r.treatment_name,r.treatment_code,r.id,r.is_available?'可用':'停用'],standards:[r.treatment_name,'¥'+money(r.unit_price)+' / '+r.unit_name,r.duration_minutes+' 分钟','版本 '+r.revision_no],standard_drafts:[r.treatment_name,'¥'+money(r.unit_price),r.duration_minutes+' 分钟',status],
 phases:[r.phase_title,r.plan_no,clinicName(r.responsible_clinic_id),status],followups:[r.label,clinicName(r.responsible_clinic_id),r.next_contact_at?dayLabel(r.next_contact_at)+' '+clock(r.next_contact_at):'待安排',r.closed_at?'已办结':format(r.contact_progress)],calendars:[r.work_date,range(r.starts_at,r.ends_at),clinicName(r.clinic_id),r.is_open?'营业':'关闭'],operatories:[r.operatory_name,r.operatory_code,clinicName(r.clinic_id),status],
 cost_sources:[r.source_document_no,format(r.cost_category),r.document_date,'原始行 '+r.source_line_no],cost_revisions:['来源修订 '+r.revision_no,'¥'+money(r.source_amount),r.correction_reason||'初次登记',r.validity||'留存'],allocations:[r.label,'¥'+money(r.allocated_amount),r.allocation_basis,status],submissions:[r.label,doctorName(r.dentist_id)+' · '+clinicName(r.clinic_id),r.submitted_at?dayLabel(r.submitted_at):'已报送',status],reports:[r.label,r.quarter_id,'版本 '+r.revision_no,status],
 accounts:[r.display_name,r.login_name,format(r.account_kind),r.is_enabled?'启用':'停用'],scopes:[r.label,format(r.scope_kind),r.clinic_id?clinicName(r.clinic_id):r.patient_id?'患者 '+r.patient_id:'集团范围',r.revoked_at?'已撤销':'有效']
 };return (result[dataset]||[r.label||r.id,'—','—',status]).map(value)
}
export const fieldNames:Record<string,string>={full_name:'姓名',sex_code:'性别',change_reason:'变更原因',substance_name:'过敏物质',reporter_name:'报告人',account_no:'患者档案编号',birth_date:'出生日期',phone:'联系电话',email:'电子邮箱',billing_address:'账单地址',postal_address:'门店地址',allergy_declaration:'过敏申报',clinic_name:'门店',floor_area:'使用面积（平方米）',opened_on:'开业日期',closed_on:'停业日期',professional_no:'执业编号',certificate_no:'证照编号',issuing_organisation:'发证机构',valid_from:'生效时点',valid_to:'失效时点',verification_result:'核实结论',treatment_name:'项目名称',treatment_code:'项目代码',unit_name:'计量单位',unit_price:'标准单价',duration_minutes:'预计分钟数',site_requirement:'部位要求',revision_no:'修订版本',row_version:'资料版本',phase_title:'阶段名称',clinical_condition:'临床先决条件',earliest_at:'最早可约时点',latest_at:'最晚可约时点',pause_or_end_reason:'暂停或终止依据',source_document_no:'原始凭据号',source_line_no:'原始凭据行号',evidence_reference:'凭据引用',source_amount:'来源金额',allocated_amount:'分摊金额',allocation_basis:'分摊依据',correction_reason:'更正原因',exception_reason:'例外说明',operatory_name:'资源名称',operatory_code:'资源代码',home_address:'家庭联系地址',employed_from:'入职日期',employed_to:'离职日期',login_name:'登录账号',display_name:'显示姓名',role_code:'岗位',account_kind:'主体类型',contact_purpose:'联系用途',permission_scope:'授权事项',relationship:'与患者关系',report_source:'申报来源',reaction_description:'过敏反应',zero_charge_basis:'零费用确认依据'}
