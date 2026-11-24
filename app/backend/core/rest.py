"""The concrete operation URLs printed in section 4.2 of the design report."""
import re
from django.views.decorators.csrf import csrf_exempt
from .db import one,get,rows
from .security import authenticate,require
from .http import endpoint,mutation
from . import booking,clinical,administration,finance

def identity(table,column,value):
    assert (table,column) in [('appointment','appointment_no'),('practice_duty','id'),('encounter','encounter_no'),('invoice','invoice_no'),('treatment_plan','plan_no'),('cost_source','source_document_no')]
    if str(value).isdigit():r=get(table,int(value))
    else:
        matches=rows('SELECT * FROM '+table+' WHERE '+column+'=%s LIMIT 2',[value])
        require(len(matches)<=1,'该业务编号对应多个明细，请使用具体记录编号',409)
        r=matches[0] if matches else None
    require(r,'业务编号不存在',404);return r

@csrf_exempt
@endpoint
def operation(request,b,kind,no=None,version=None,period=None):
    require(request.method=='POST','请使用POST',405);actor=authenticate(request);b=dict(b)
    if kind=='book':
        actor.allow('patient','representative','reception');b['action']='book';code='UC02';action=lambda:booking.book(actor,b)
    elif kind=='reschedule':
        actor.allow('patient','representative','reception','manager');a=identity('appointment','appointment_no',no);b.update(action='reschedule',id=a['id']);code='UC03';action=lambda:booking.change(actor,b)
    elif kind in ('replace','stop'):
        actor.allow('manager');d=identity('practice_duty','id',no);b.update(action=kind,id=d['id']);code='UC09';action=lambda:administration.duty_action(actor,b)
    elif kind in ('sign','invoice'):
        actor.allow(*(['dentist'] if kind=='sign' else ['dentist','reception','manager']));en=identity('encounter','encounter_no',no);b['encounter_id']=en['id'];b['action']='sign' if kind=='sign' else 'issue';code='UC05' if kind=='sign' else 'UC06';action=lambda:clinical.save_treatment(actor,b) if kind=='sign' else clinical.issue_invoice(actor,b)
    elif kind=='invoice-revision':
        actor.allow('manager');i=identity('invoice','invoice_no',no);b.update(action='correct',encounter_id=i['encounter_id']);code='UC06';action=lambda:clinical.issue_invoice(actor,b)
    elif kind=='plan-confirm':
        actor.allow('dentist');p=identity('treatment_plan','plan_no',no);b.update(action='confirm',id=p['id'],version=version,confirm_existing_revision=True);code='UC13';action=lambda:clinical.confirm_saved_plan(actor,b)
    elif kind=='cost-review':
        actor.allow('manager');s=identity('cost_source','source_document_no',no);rev=one('SELECT * FROM cost_revision WHERE cost_source_id=%s AND revision_no=%s',[s['id'],version]);require(rev,'费用修订不存在',404)
        ids=b.get('allocation_ids',[]);require(ids,'请明确要复核的费用分摊项');b['action']='review';code='UC11'
        def action():
            for pk in ids:
                a=get('cost_allocation',int(pk));require(a and a['cost_revision_id']==rev['id'],'分摊与指定费用修订不符');finance.cost_action(actor,dict(b,id=a['id']))
            return {'id':rev['id'],'reviewed_count':len(ids)}
    else:
        require(kind=='report-confirm','接口不存在',404);actor.allow('director');m=re.fullmatch(r'(\d{4})-Q?([1-4])',period);require(m,'季度格式应为2026-Q4');q=one('SELECT id FROM fiscal_quarter WHERE calendar_year=%s AND quarter_no=%s',[int(m[1]),int(m[2])]);require(q,'季度尚未建立',404);b.update(action='confirm',quarter_id=q['id']);code='UC12';action=lambda:finance.report_action(actor,b)
    return mutation(actor,code,request,b,action)
