"""Target the staff-side gaps that affected the desk workflow."""
import unittest
from unittest.mock import patch

import test_integration as base
from core.db import one, get

class StaffWorkflowTests(unittest.TestCase):
    setUpClass=classmethod(base.WorkflowTests.setUpClass.__func__)
    setUp=base.WorkflowTests.setUp
    rollback=base.WorkflowTests.rollback
    post=base.WorkflowTests.post
    booking=base.WorkflowTests.booking

    def test_clinic_resource_contains_edit_fields(self):
        response=self.clients['business'].get('/api/workspace')
        self.assertEqual(response.status_code,200)
        clinic=response.json()['resources']['clinics'][0]
        for field in ('id','clinic_name','postal_address','phone','email','floor_area','opened_on','row_version'):
            self.assertIn(field,clinic)
        response=self.post('business','UC07',dict(id=clinic['id'],row_version=clinic['row_version'],
            clinic_name='合成门店校订',email=clinic['email'],floor_area=clinic['floor_area']))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['id'],clinic['id'])

    def test_dentist_reads_own_fee_source(self):
        base.WorkflowTests.test_22_complete_clinical_invoice(self)
        encounter=one('SELECT id FROM encounter ORDER BY id DESC LIMIT 1')
        path='/api/billing/'+str(encounter['id'])
        result=self.clients['dentist'].get(path)
        self.assertEqual(result.status_code,200,result.content)
        body=result.json()
        self.assertTrue(body['invoice_versions'][0]['lines'])
        self.assertFalse(body['clinical_narrative_included'])
        self.assertEqual(self.clients['patient'].get(path).status_code,403)

    def test_head_office_account_candidates_have_minimal_profile(self):
        for role in ('business','director'):
            row=self.clients[role].get('/api/workspace').json()['resources']['account_patients'][0]
            self.assertEqual(set(row),{'id','full_name','account_no'})
        row=self.clients['patient'].get('/api/workspace').json()
        self.assertNotIn('account_patients',row['resources'])

if __name__=='__main__':unittest.main(verbosity=2)
