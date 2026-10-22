"""Reference-free local LP repairs and budgeted binary evidence acquisition.

The risk is disagreement on a finite candidate-derived witness panel. It is
not a population error probability or an unconditional guarantee of correctness.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from functools import lru_cache
from hashlib import sha256
import json
import random

import numpy as np
from decision_geometry import compile_model, _analysis, _face_rows, _inclusion_witnesses


@lru_cache(maxsize=8192)
def geometry(compiled):
    return _analysis(compiled)


def fingerprint(model):
    a = geometry(compile_model(model))
    return (a['status'], a['vertices'], a['rays'], a['optimal_vertices'], a['optimal_rays'])


def membership(model, kind, point):
    compiled = compile_model(model)
    point = tuple(map(F, point))
    feasible = all(a*point[0]+b*point[1] <= c for a,b,c in compiled.rows)
    if kind == 'feasibility':
        return feasible
    if kind != 'optimality':
        raise ValueError('Unknown evidence kind')
    info = geometry(compiled)
    return feasible and info['status']=='optimal' and sum(a*x for a,x in zip(compiled.objective,point))==info['value']


def row_key(row):
    return compile_model({'sense':'min','objective':[0,0],'constraints':[row]}).rows


def candidate_bank(initial, peer):
    """Propose all single constraint edits, without text, labels or a reference."""
    proposals = []
    if initial is not None:
        proposals.append((0,'A',deepcopy(initial)))
    if peer is not None:
        proposals.append((2,'B',deepcopy(peer)))
    base = initial if initial is not None else peer
    if base is not None:
        offset = 0 if initial is not None else 2
        rows = sorted(base['constraints'],key=row_key)
        others = sorted(peer['constraints'],key=row_key) if peer is not None else []
        for i in range(len(rows)):
            model = deepcopy(base)
            model['constraints'] = deepcopy(rows[:i]+rows[i+1:])
            proposals.append((offset+1,f'delete:{i}',model))
        for j,row in enumerate(others):
            model = deepcopy(base)
            model['constraints'] = deepcopy(rows+[row])
            proposals.append((offset+1,f'add:{j}',model))
            for i in range(len(rows)):
                model = deepcopy(base)
                model['constraints'] = deepcopy(rows[:i]+[row]+rows[i+1:])
                proposals.append((offset+1,f'replace:{i}:{j}',model))
        if peer is not None:
            model = deepcopy(base)
            model['sense'],model['objective'] = peer['sense'],deepcopy(peer['objective'])
            proposals.append((offset+1,'objective',model))
    bank, seen = [], {}
    for cost,edit,model in sorted(proposals,key=lambda x:(x[0],x[1])):
        try:
            key = fingerprint(model)
        except (ValueError,TypeError):
            continue
        if key in seen:
            bank[seen[key]]['aliases'].append(edit)
            continue
        seen[key] = len(bank)
        bank.append({'model':model,'cost':cost,'edit':edit,'aliases':[edit]})
    initial_index = next((i for i,c in enumerate(bank) if 'A' in c['aliases']),None)
    peer_index = next((i for i,c in enumerate(bank) if 'B' in c['aliases']),None)
    return bank,initial_index,peer_index


def prepare(initial, peer):
    bank, initial_index, peer_index = candidate_bank(initial,peer)
    models = [compile_model(c['model']) for c in bank]
    infos = [geometry(c) for c in models]
    all_rows = tuple(sorted({r for c in models for r in c.rows}))
    all_faces = tuple(sorted({r for c,a in zip(models,infos) for r in _face_rows(c,a)}))
    points = set()
    for info in infos:
        for kind, vertices, rays, target in (
            ('feasibility',info['vertices'],info['rays'],all_rows),
            ('optimality',info['optimal_vertices'],info['optimal_rays'],all_faces)):
            points.update((kind,p) for p in vertices)
            for witness in _inclusion_witnesses(vertices,rays,target,kind,'candidate','panel'):
                points.add((kind,tuple(map(F,witness['point']))))
    def complexity(item):
        kind,point=item
        return (kind,sum(abs(x.numerator).bit_length()+x.denominator.bit_length() for x in point),point)
    queries, patterns, seen = [], [], set()
    for kind,point in sorted(points,key=complexity):
        pattern = tuple(membership(c['model'],kind,point) for c in bank)
        if not any(pattern) or all(pattern) or (kind,pattern) in seen:
            continue
        seen.add((kind,pattern))
        queries.append({'kind':kind,'point':list(map(str,point))})
        patterns.append(pattern)
    predictions = np.array(patterns,dtype=bool).T if patterns else np.zeros((len(bank),0),dtype=bool)
    distance = np.sum(predictions[:,None,:] != predictions[None,:,:],axis=2,dtype=np.int32)
    if len(bank)>1 and np.any(distance[np.triu_indices(len(bank),1)]==0):
        raise AssertionError('Witness panel failed to separate distinct decision contracts')
    return {'bank':bank,'initial_index':initial_index,'peer_index':peer_index,
            'queries':queries,'predictions':predictions,'distance':distance}


def survivors(prepared, evidence, error_budget=0):
    if error_budget < 0:
        raise ValueError('Negative error budget')
    mismatch=np.zeros(len(prepared['bank']),dtype=int)
    for qid,label in evidence:
        if label is not None:
            if type(label) is not bool:
                raise ValueError('Evidence label must be bool or missing')
            mismatch += prepared['predictions'][:,qid] != label
    return list(np.flatnonzero(mismatch<=error_budget))


def choose(prepared, remaining, selector='gated'):
    initial=prepared['initial_index']
    if not remaining:
        return initial,True,None
    if selector=='local':
        return min(remaining,key=lambda i:(prepared['bank'][i]['cost'],i)),False,None
    risk={i:int(max(prepared['distance'][i,j] for j in remaining)) for i in remaining}
    best=min(remaining,key=lambda i:(risk[i],prepared['bank'][i]['cost'],i))
    if selector=='minimax':
        return best,False,risk[best]
    if selector!='gated':
        raise ValueError('Unknown selector')
    baseline=(int(max(prepared['distance'][initial,j] for j in remaining))
              if initial is not None else len(prepared['queries'])+1)
    if risk[best] < baseline:
        return best,False,risk[best]
    return initial,True,baseline


def available(prepared, mode):
    if mode not in ('feasibility','joint'):
        raise ValueError('Unknown query mode')
    return [i for i,q in enumerate(prepared['queries']) if mode=='joint' or q['kind']=='feasibility']


def fixed_sequence(prepared, mode, budget=8):
    """Greedy pair coverage using model predictions only, before any answers."""
    n=len(prepared['bank'])
    uncovered=np.triu(np.ones((n,n),dtype=bool),1)
    pending=available(prepared,mode)
    selected=[]
    while pending and len(selected)<budget:
        def score(q):
            p=prepared['predictions'][:,q]
            return int(np.sum(uncovered & (p[:,None]!=p[None,:])))
        q=max(pending,key=lambda i:(score(i),-i))
        if score(q)==0:
            break
        selected.append(q); pending.remove(q)
        p=prepared['predictions'][:,q]
        uncovered &= p[:,None]==p[None,:]
    return selected


def query_choice(prepared, remaining, asked, mode, policy, rng):
    pending=[]
    for q in available(prepared,mode):
        if q in asked:
            continue
        k=int(np.sum(prepared['predictions'][remaining,q]))
        if 0<k<len(remaining):
            pending.append((q,k))
    if not pending:
        return None
    if policy=='random':
        return rng.choice(pending)[0]
    if policy=='maxsplit':
        return max(pending,key=lambda q:(q[1]*(len(remaining)-q[1]),-q[0]))[0]
    if policy!='risk':
        raise ValueError('Unknown query policy')
    def residual(q):
        total=0
        for answer in (False,True):
            group=[i for i in remaining if bool(prepared['predictions'][i,q])==answer]
            loss=min(int(max(prepared['distance'][i,j] for j in group)) for i in group)
            total += len(group)*loss
        return total
    return min(pending,key=lambda q:(residual(q[0]),-q[1]*(len(remaining)-q[1]),q[0]))[0]


def adaptive(prepared, oracle, mode, policy, seed, budget=8):
    """The only semantic access is the oracle callback on the selected question."""
    evidence, states = [], []
    rng=random.Random(seed)
    states.append({'budget':0,'selected':prepared['initial_index'],'abstained':True,
                   'attempts':0,'evidence':[],'remaining':len(prepared['bank']),'loss':None})
    exhausted=False
    for b in range(1,budget+1):
        remaining=survivors(prepared,evidence)
        q=None if exhausted else query_choice(prepared,remaining,{x[0] for x in evidence},mode,policy,rng)
        if q is None:
            exhausted=True
        else:
            label=oracle(deepcopy(prepared['queries'][q]))
            evidence.append((q,label))
        remaining=survivors(prepared,evidence)
        selected,abstained,loss=choose(prepared,remaining)
        states.append({'budget':b,'selected':selected,'abstained':abstained,
                       'attempts':len(evidence),'evidence':list(evidence),'remaining':len(remaining),'loss':loss})
    return states


def evidence_variant(sequence, labels, scenario, identifier, seed):
    evidence=[]
    for pos,(q,label) in enumerate(zip(sequence,labels)):
        if scenario=='missing_half':
            digest=sha256(f'{seed}:{identifier}:{q}'.encode()).digest()
            label=None if digest[0]<128 else label
        elif scenario=='one_wrong':
            label=not label if pos==min(1,len(sequence)-1) else label
        elif scenario!='clean':
            raise ValueError('Unknown corruption scenario')
        evidence.append((q,label))
    return evidence


def serializable(prepared):
    return {k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in prepared.items()}
