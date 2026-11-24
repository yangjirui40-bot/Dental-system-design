import { localDay, type Row } from './workspace'

export type StaffTask = {
  code: string
  action?: string
  dataset?: string
  id?: number
  label: string
  subject?: string
}

export const staffQuickActions: Record<string, StaffTask[]> = {
  reception: [
    {code:'UC02', label:'协助预约'},
    {code:'UC01', action:'save', label:'新建患者档案'},
    {code:'UC04', action:'arrive', label:'办理到店报到'},
    {code:'UC03', dataset:'followups', action:'contact', label:'登记待约联系'},
    {code:'UC06', label:'查看结算及补开'},
    {code:'UC16', action:'create', label:'开通患者或代办账号'},
  ],
  dentist: [
    {code:'UC04', action:'start', label:'确认实际接诊'},
    {code:'UC05', label:'诊疗签署与草稿'},
    {code:'UC01', action:'allergy', label:'核实患者过敏'},
    {code:'UC13', label:'编制与放行治疗阶段'},
    {code:'UC06', label:'查看结算与更正依据'},
  ],
  manager: [
    {code:'UC09', action:'draft', label:'安排医生出诊'},
    {code:'UC15', action:'calendar', label:'设置营业时段'},
    {code:'UC15', dataset:'operatories', action:'operatory', label:'维护诊疗位'},
    {code:'UC03', dataset:'followups', action:'assign', label:'移交待接续事项'},
    {code:'UC06', label:'审核非标准收费与更正'},
    {code:'UC11', dataset:'allocations', label:'复核本店费用'},
    {code:'UC12', label:'查看本店季度经营'},
  ],
  business: [
    {code:'UC07', action:'save', label:'新增门店'},
    {code:'UC08', action:'employee', label:'新增职员档案'},
    {code:'UC08', dataset:'dentists', action:'qualification', label:'核实牙医资质'},
    {code:'UC09', action:'draft', label:'编排跨店出诊'},
    {code:'UC10', action:'catalog', label:'建立治疗项目'},
    {code:'UC10', action:'draft', label:'编制项目标准草案'},
    {code:'UC16', action:'create', label:'开通员工账号'},
  ],
  finance: [
    {code:'UC11', action:'source', label:'录入费用及分摊'},
    {code:'UC11', action:'submission', label:'提交费用齐备声明'},
  ],
  director: [
    {code:'UC10', action:'approve', dataset:'standard_drafts', label:'批准项目标准'},
    {code:'UC16', action:'grant', label:'批准员工岗位授权'},
    {code:'UC12', label:'查看并确认集团季度'},
    {code:'UC17', label:'查阅集团操作日志'},
  ],
}

const changeable = ['booked','arrived','unfulfilled']

export function actionsForRecord(code:string, dataset:string, row:Row, role:string, now:string): StaffTask[] {
  const use = (action:string,label:string) => ({ code, action, label, dataset, id:row.id })
  switch (code) {
    case 'UC01':
      if (dataset === 'patients') return [
        ...(role==='reception'?[use('save','修改患者资料'),use('contact','登记联系人'),use('authority','核实代办授权')]:[]),
        use('allergy',role==='dentist'?'核实过敏':'登记过敏申报'),
      ]
      return dataset==='authorities'&&!row.revoked_at ? [use('revoke-authority','撤销该授权')] : []
    case 'UC03':
      if (dataset==='followups'&&!row.closed_at) return role==='manager'?[use('assign','移交跟进')]:[use('contact','登记联系结果')]
      return dataset==='appointments'&&changeable.includes(row.resolution)?[use('reschedule','改期'),use('cancel','取消预约')]:[]
    case 'UC04':
      if (dataset!=='appointments') return []
      if (role==='dentist') {
        if (row.resolution==='arrived') return [use('start','核实并接诊')]
        if (row.resolution==='seen') return [use('correct','补正接诊时间')]
        return []
      }
      return [
        ...(row.resolution==='booked'&&localDay(row.starts_at)===localDay(now)?[use('arrive','记录到店')]:[]),
        ...(row.resolution==='booked'&&Date.parse(row.ends_at)<Date.parse(now)?[use('no_show','核实未到')]:[]),
        ...(row.resolution==='arrived'?[use('leave','登记到店未接诊离开')]:[]),
      ]
    case 'UC05':
      return dataset==='encounters'?[use('draft','编辑临床记录'),use('sign','核对并签署')]:[]
    case 'UC06':
      if (!['encounters','invoices'].includes(dataset)) return []
      if (role==='manager') return dataset==='invoices'?[use('correct','复核结算更正')]:[use('approve-price','核对拟收价格')]
      if (role==='dentist'&&dataset==='invoices') return [use('prepare-correction','提交更正待主管复核')]
      return dataset==='encounters'?[use('issue','核对并补开结算')]:[]
    case 'UC07':
      return dataset==='clinics'?[use('save','编辑门店'),use('manager','登记主管任职')]:[]
    case 'UC08':
      if (dataset==='employees') return [use('employee','编辑职员资料'),use('dentist','建立牙医身份')]
      if (dataset==='dentists') return [use('qualification','核实专业资质')]
      if (dataset==='qualifications'&&row.verification_result==='verified') return [use('revoke','办理资质撤销')]
      return []
    case 'UC10':
      if (role==='director') return dataset==='standard_drafts'?[use('approve','批准该标准'),use('reject','退回草案')]:[]
      if (dataset==='catalog') return [use('draft','编制项目标准'),...(row.is_available?[use('disable','停用该项目')]:[])]
      return dataset==='standards'?[use('draft','编制新版本')]:[]
    case 'UC11':
      if (role==='manager') {
        if (row.review_state!=='pending'&&row.review_state!=='disputed') return []
        if(dataset==='allocations') return [use('review','复核该分摊')]
        if(dataset==='submissions') return [use('review-submission','复核齐备声明')]
      }
      return role==='finance'&&dataset==='cost_sources'?[use('source','修订费用来源')]:[]
    case 'UC13':
      if (dataset==='encounters') return [use('draft','编制阶段方案')]
      return dataset==='phases'?[use('phase','办理阶段状态'),use('confirm','核对方案及先决条件')]:[]
    case 'UC15':
      if (dataset==='calendars') return [use('calendar','编辑营业时段')]
      if (dataset==='operatories') return [use('operatory','编辑诊疗位')]
      return []
    case 'UC16':
      if(dataset==='scopes'&&!row.revoked_at) return [use('revoke','撤销该岗位')]
      if(dataset==='accounts') return [
        ...(role==='director'&&row.is_enabled?[use('grant','授予岗位与范围')]:[]),
        ...(role==='reception'&&row.account_kind==='representative'&&row.is_enabled?[use('grant','授权代办患者')]:[]),
        use('password','协助重置密码'), use(row.is_enabled?'disable':'enable',row.is_enabled?'停用账号':'启用账号'),
      ]
      return []
    default:
      return []
  }
}

export function operationFields(code:string, action:string, dataset:string, row:Row, keys:string[]): Row {
  const source = row.patient || row
  const fields: Row = {}
  const copy = () => {
    for (const key of [...keys,'row_version']) if (source[key]!=null) fields[key] = source[key]
    fields.id = source.id
  }
  if (code==='UC01') {
    if (action==='save'&&dataset==='patients') copy()
    else fields.id = dataset==='patients'?source.id:source.patient_id
    if (action==='revoke-authority'&&dataset==='authorities') fields.authority_id=source.id
  } else if (code==='UC03') {
    fields.id=source.id;fields.row_version=source.row_version
  } else if (code==='UC04') {
    fields.appointment_id=source.appointment_id??source.id
    if(action==='correct') for (const key of ['started_at','arrived_at','ended_at']) if(source[key]) fields[key]=source[key]
  } else if (['UC05','UC06','UC13'].includes(code)) {
    fields.encounter_id=source.encounter_id??source.origin_encounter_id??(dataset==='encounters'?source.id:null)
    if (code==='UC13'&&dataset==='phases') fields.phase_id=source.id
  } else if (code==='UC07') {
    if(action==='save') copy()
    else fields.clinic_id=source.id
  } else if (code==='UC08') {
    if (action==='employee') copy()
    else if(action==='dentist') fields.employee_id=source.id
    else if(action==='qualification') fields.dentist_id=source.id
    else if(action==='revoke') fields.id=source.id
  } else if (code==='UC10') {
    if(action==='draft') {
      if (dataset==='standards') for(const key of keys) if(!['id','valid_from','valid_to'].includes(key)&&source[key]!=null) fields[key]=source[key]
      fields.treatment_id=dataset==='catalog'?source.id:source.treatment_id
    } else fields.id=source.id
  } else if(code==='UC11') {
    if(action==='source') {
      for(const key of keys) if(source[key]!=null) fields[key]=source[key]
      fields.source_id=source.id
    } else fields.id=source.id
  } else if(code==='UC15') copy()
  else if(code==='UC16') fields[action==='grant'?'account_id':'id']=source.id
  return fields
}
