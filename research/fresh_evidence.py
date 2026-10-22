"""One fresh separating question before replacing a delivered LP model.

Conditional no-regression property: if the initial contract is correct and the
oracle answers the selected membership query truthfully, this rule never changes
it to an incorrect contract. This does not certify an initially incorrect model
or an accepted repair: two incorrect models can disagree at the queried point.
"""
from copy import deepcopy
import evidence_repair as method


def fresh_question(initial,proposal,mode='feasibility'):
    if mode not in ('feasibility','joint'): raise ValueError('Unknown query mode')
    if initial is None or proposal is None: return None
    panel=method.prepare(initial,proposal)
    a,b=panel['initial_index'],panel['peer_index']
    if a==b: return None
    for q in method.available(panel,mode):
        if panel['predictions'][a,q]!=panel['predictions'][b,q]:
            return deepcopy(panel['queries'][q])
    return None


def deliver(initial,proposal,oracle,mode='feasibility'):
    """The oracle sees one point and query kind; no gold model enters this rule."""
    if proposal is None:
        return {'model':initial,'accepted':False,'reason':'invalid_proposal','queries':[]}
    if initial is None:
        return {'model':proposal,'accepted':True,'reason':'initial_invalid','queries':[]}
    if method.fingerprint(initial)==method.fingerprint(proposal):
        return {'model':proposal,'accepted':True,'reason':'same_contract','queries':[]}
    question=fresh_question(initial,proposal,mode)
    if question is None:
        return {'model':initial,'accepted':False,'reason':'no_permitted_separator','queries':[]}
    answer=oracle(deepcopy(question))
    if answer is not None and type(answer) is not bool: raise ValueError('Oracle must return bool or missing')
    old=method.membership(initial,question['kind'],question['point'])
    new=method.membership(proposal,question['kind'],question['point'])
    assert old!=new
    accepted=answer is not None and answer==new and answer!=old
    return {'model':proposal if accepted else initial,'accepted':accepted,
            'reason':'old_falsified' if accepted else 'old_retained',
            'queries':[{**question,'answer':answer,'initial_label':old,'proposal_label':new}]}
