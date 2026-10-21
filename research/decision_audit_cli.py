"""Offline conditional audit of two aligned two-variable LP formulations.

Usage: python research/decision_audit_cli.py input.json --output audit.json
Input: {"candidate_A": IR, "candidate_B": IR,
        "text": optional source text, "variables": optional ordered names}.
No API, credentials, reference answer or source-code execution is used.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from decision_geometry import compare_models
from decision_semantic_guard import audit_model


def audit(payload):
    if not isinstance(payload, dict):
        raise ValueError('input must be an object')
    allowed = {'candidate_A', 'candidate_B', 'text', 'variables'}
    if set(payload)-allowed or not {'candidate_A','candidate_B'} <= set(payload):
        raise ValueError('expected candidate_A, candidate_B, and optional text/variables only')
    comparison = compare_models(payload['candidate_A'],payload['candidate_B'])
    result={'schema':'conditional-decision-audit.v1','comparison':comparison,
            'status':'agreement_without_semantic_certification' if comparison['equivalent'] else 'model_disagreement',
            'scope':'Continuous nonnegative two-variable LPs with aligned variable meanings; exact rational arithmetic.',
            'warning':'Agreement cannot certify the source interpretation; disagreement does not identify the correct candidate.'}
    if ('text' in payload) != ('variables' in payload):
        raise ValueError('text and variables must be supplied together')
    if 'text' in payload:
        result['source_checks']={arm:audit_model(payload['text'],payload['variables'],payload[arm])
                                 for arm in ('candidate_A','candidate_B')}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path); parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        result=audit(json.loads(args.input.read_text('utf-8-sig')))
    except (ValueError,KeyError,TypeError) as error:
        result={'status':'invalid_input','error':str(error),'certified':False}
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream: stream.write(text)
    else: print(text,end='')
    raise SystemExit(2 if result['status']=='invalid_input' else 0)
