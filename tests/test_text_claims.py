from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from text_claims import extract,contradicts

class TextClaimTests(unittest.TestCase):
    def test_variable_order_and_exact_spans(self):
        text='It takes 30 minutes to make one apple pie and 40 minutes to make a blueberry pie. The business only operates for 4500 minutes per week.'
        claims=extract(text,['blueberry pies','apple pies']);self.assertEqual(len(claims),1)
        self.assertEqual(claims[0]['row'],{'a':['40','30'],'op':'<=','b':'4500'})
        for s in claims[0]['spans']:self.assertEqual(text[s['start']:s['end']],s['text'])

    def test_ambiguous_alias_and_multiple_capacities_abstain(self):
        text='It takes 30 minutes to make one apple pie and 40 minutes to make a blueberry pie. It only operates for 4500 minutes per week.'
        self.assertEqual(extract(text,['pie','pie']),[])
        self.assertEqual(extract(text+' It only operates for 500 minutes per day.',['apple pies','blueberry pies']),[])

    def test_partial_upper_bound_finds_wrong_direction_with_exact_witness(self):
        claim=extract('The truck can only prepare up to 120 items in total.',['tea','juice'])[0]
        wrong={'sense':'max','objective':[1,1],'constraints':[{'a':[1,1],'op':'>=','b':120}]}
        right={'sense':'max','objective':[1,1],'constraints':[claim['row']]}
        self.assertIsNotNone(contradicts(wrong,claim)['witness'])
        self.assertIsNone(contradicts(right,claim)['witness'])

    def test_resource_names_and_variable_binding(self):
        text='George has to collect 50 units of wood and 60 units of metal. For each hour in area one that he spends, he gets 2 units of wood and 5 units of metal. For each hour in area two that he spends, he gets 8 units of wood and 3 units of metal.'
        c=extract(text,['area two','area one']);self.assertEqual(len(c),2)
        self.assertEqual(c[0]['row'],{'a':['8','2'],'op':'>=','b':'50'})
        self.assertEqual(c[1]['row'],{'a':['3','5'],'op':'>=','b':'60'})

    def test_narrow_grammar_does_not_guess_unspecified_claims(self):
        self.assertEqual(extract('Prepare many items and work efficiently.',['x','y']),[])
        self.assertEqual(extract('The truck can only prepare up to 120 items in total.',['x','y','z']),[])

if __name__=='__main__':unittest.main()
