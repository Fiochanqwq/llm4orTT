import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from decision_audit_cli import audit

class AuditCLITests(unittest.TestCase):
    def test_agreement_is_not_semantic_certificate(self):
        model={'sense':'min','objective':[1,1],'constraints':[]}
        result=audit({'candidate_A':model,'candidate_B':model})
        self.assertEqual(result['status'],'agreement_without_semantic_certification')
        self.assertEqual(result['comparison']['witnesses'],[])

    def test_unknown_reference_input_rejected(self):
        with self.assertRaises(ValueError): audit({'candidate_A':{},'candidate_B':{},'reference':{}})

    def test_disagreement_has_finite_witness(self):
        a={'sense':'min','objective':[1,1],'constraints':[{'a':[1,1],'op':'<=','b':3}]}
        b={'sense':'min','objective':[1,1],'constraints':[{'a':[1,1],'op':'<=','b':4}]}
        result=audit({'candidate_A':a,'candidate_B':b})
        self.assertEqual(result['status'],'model_disagreement')
        self.assertTrue(result['comparison']['witnesses'])

if __name__=='__main__': unittest.main()
