"""UC01 completeness checks using the frozen patient/contact/allergy model."""
import re
from .db import one,insert
from .security import require

def emergency_details(body):
    keys=('emergency_name','emergency_phone','emergency_relationship')
    if not any(body.get(k) for k in keys):return None
    name=str(body.get('emergency_name','')).strip()
    phone=str(body.get('emergency_phone','')).strip()
    relationship=str(body.get('emergency_relationship','')).strip()
    require(1<=len(name)<=100 and 7<=len(phone)<=40 and re.fullmatch(r'[+0-9()\s-]+',phone),'请完整填写紧急联系人姓名及有效电话')
    require(1<=len(relationship)<=160,'请填写紧急联系人与患者的关系')
    return dict(full_name=name,phone=phone,relationship=relationship)

def save_emergency(patient_id,details,account_id,employee_id,now):
    latest=one("SELECT * FROM patient_contact WHERE patient_id=%s AND contact_purpose='emergency' ORDER BY id DESC LIMIT 1",[patient_id])
    require(details or latest,'至少保留一名紧急联系人的姓名及电话')
    if details and (not latest or any(latest[k]!=v for k,v in details.items())):
        # Append rather than changing contacts referenced by prior consent/authority.
        insert('patient_contact',dict(**details,patient_id=patient_id,contact_purpose='emergency',recorded_by=employee_id,recorded_account_id=account_id,recorded_at=now))

def declaration(value,patient_id=None):
    require(value in ('unknown','denied','reported'),'请选择未采集、否认已知过敏或已逐项申报')
    active=one("SELECT a.id FROM patient_allergy a JOIN LATERAL (SELECT verification_result FROM allergy_revision WHERE allergy_id=a.id ORDER BY revision_no DESC LIMIT 1) r ON true WHERE a.patient_id=%s AND r.verification_result<>'refuted' LIMIT 1",[patient_id]) if patient_id else None
    require(value!='reported' or patient_id and one('SELECT id FROM patient_allergy WHERE patient_id=%s LIMIT 1',[patient_id]),'请先逐项登记过敏物质、反应及申报来源')
    require(value=='reported' or not active,'仍有尚未被牙医排除的过敏项，不能用未采集或否认状态覆盖；请由牙医逐项核实')
    return value
