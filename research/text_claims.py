"""Narrow, source-grounded constraint extraction, independent of reference models.

Supported grammar is intentionally explicit. Each output includes exact input
spans, coefficients and variable binding. Unrecognized clauses produce no claim.
A model contradiction is a concrete feasible witness violating a stated claim;
this is a partial text check, not a complete semantic model or corrected label.
"""
from fractions import Fraction as F
import re
from decision_geometry import compile_model,_analysis,_inclusion_witnesses

NUMBER=r'(\d+(?:,\d{3})*(?:\.\d+)?)'

def number(s):return str(F(s.replace(',','')))

def tokens(s):
    return [w[:-1] if w.endswith('s') else w for w in re.findall(r'[a-z]+',s.lower())]

def bind(phrase,variables):
    words=tokens(phrase);matches=[]
    for i,name in enumerate(variables):
        target=tokens(name)
        if target and len(words)>=len(target) and words[-len(target):]==target:matches.append(i)
    return matches[0] if len(matches)==1 else None

def extract(text,variables):
    if len(variables)!=2:return []
    claims=[]
    def add(rule,row,matches,bindings):
        spans=[{'start':m.start(),'end':m.end(),'text':text[m.start():m.end()]} for m in matches]
        claims.append({'rule':rule,'row':row,'spans':spans,'variable_bindings':bindings})
    # A total count explicitly caps all item types in the supplied catalog.
    for m in re.finditer(r'can only prepare up to '+NUMBER+r' items(?: in total)?',text,re.I):
        add('explicit_total_capacity',{'a':['1','1'],'op':'<=','b':number(m[1])},[m],{'total':list(variables)})
    pattern=r'It takes '+NUMBER+r' minutes to make (?:one|a|an) ([^.,;]+?) and '+NUMBER+r' minutes to make (?:one|a|an) ([^.,;]+)[.]'
    capacities=list(re.finditer(r'only operates for '+NUMBER+r' minutes per (?:week|day)',text,re.I))
    for m in re.finditer(pattern,text,re.I):
        i,j=bind(m[2],variables),bind(m[4],variables)
        if i is None or j is None or i==j or len(capacities)!=1:continue
        a=['0','0'];a[i]=number(m[1]);a[j]=number(m[3]);cap=capacities[0]
        add('item_time_capacity',{'a':a,'op':'<=','b':number(cap[1])},[m,cap],{m[2]:i,m[4]:j})
    # Resource collection: an explicit total requirement and complete rates for both areas.
    needs=list(re.finditer(r'has to collect '+NUMBER+r' units of ([a-z]+) and '+NUMBER+r' units of ([a-z]+)',text,re.I))
    rates=list(re.finditer(r'For each hour in ([^,]+?) that (?:he|she|they) spends?, (?:he|she|they) gets? '+NUMBER+r' units of ([a-z]+) and '+NUMBER+r' units of ([a-z]+)',text,re.I))
    if len(needs)==1 and len(rates)==2:
        mapped=[bind(m[1],variables) for m in rates]
        need=needs[0];resources=[need[2].lower(),need[4].lower()]
        if set(mapped)=={0,1} and all({m[3].lower(),m[5].lower()}==set(resources) for m in rates):
            for resource,rhs in zip(resources,(need[1],need[3])):
                a=['0','0']
                for m,index in zip(rates,mapped):a[index]=number(m[2] if m[3].lower()==resource else m[4])
                add('resource_requirement',{'a':a,'op':'>=','b':number(rhs)},[need]+rates,{'resource':resource,'variables':list(variables)})
    return claims

def contradicts(model,claim):
    if model is None:return {'checked':False,'witness':None}
    lp=compile_model(model);g=_analysis(lp)
    target=compile_model({'sense':'min','objective':[0,0],'constraints':[claim['row']]}).rows
    witnesses=_inclusion_witnesses(g['vertices'],g['rays'],target,'feasibility','model','text_claim')
    if not witnesses:return {'checked':True,'witness':None,'model_status':g['status']}
    w=witnesses[0];point=list(map(F,w['point']));row=claim['row']
    lhs=sum(F(str(a))*x for a,x in zip(row['a'],point));rhs=F(str(row['b']))
    satisfied={'<=':lhs<=rhs,'>=':lhs>=rhs,'=':lhs==rhs}[row['op']]
    assert not satisfied
    assert all(a*point[0]+b*point[1]<=c for a,b,c in lp.rows)
    return {'checked':True,'witness':w['point'],'lhs':str(lhs),'op':row['op'],'rhs':str(rhs),'model_status':g['status']}
