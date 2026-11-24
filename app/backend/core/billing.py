"""UC06 source review: financial facts without clinical narrative."""
from .db import get,one,rows
from .security import authenticate,require
from .http import endpoint

@endpoint
def review(request,body,pk):
    require(request.method=='GET','请使用GET',405)
    actor=authenticate(request);actor.allow('reception','manager','dentist')
    encounter=get('encounter',pk);require(encounter,'就诊不存在',404)
    appointment=get('appointment',encounter['appointment_id']);actor.clinic_access(appointment['clinic_id'])
    if actor.role=='dentist':require(appointment['dentist_id']==actor.employee,'只能核对本人就诊的结算来源',403)
    patient=get('patient',appointment['patient_id'])
    latest=one('SELECT id,revision_no,signature_state,signed_at FROM clinical_note WHERE encounter_id=%s ORDER BY revision_no DESC LIMIT 1',[pk])
    items=rows('''SELECT r.treatment_id,r.standard_id,r.site_description,r.actual_quantity,r.charged_unit_price,
      r.implementation_result,r.performed_at,r.price_approved_by,r.price_approval_basis,s.treatment_name,s.unit_name,s.unit_price AS standard_price
      FROM treatment t JOIN LATERAL (SELECT * FROM treatment_revision x WHERE x.treatment_id=t.id ORDER BY revision_no DESC LIMIT 1) r ON true
      JOIN treatment_standard s ON s.id=r.standard_id WHERE t.encounter_id=%s ORDER BY t.line_no''',[pk])
    versions=rows('''SELECT r.* FROM invoice_revision r JOIN invoice i ON i.id=r.invoice_id
      WHERE i.encounter_id=%s ORDER BY r.revision_no DESC''',[pk])
    for version in versions:
        version['lines']=rows('SELECT * FROM invoice_line WHERE invoice_revision_id=%s ORDER BY line_no',[version['id']])
    return {'encounter_id':pk,'encounter_no':encounter['encounter_no'],'patient_name':patient['full_name'],
      'latest_note':latest,'items':items,'invoice_versions':versions,'clinical_narrative_included':False}
