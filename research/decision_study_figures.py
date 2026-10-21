"""Provisional research figures; source values are never edited for display."""
from pathlib import Path
import importlib.util
import sys
import json
import os
os.environ.setdefault('MPLBACKEND','Agg')
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'实验/决策契约研究_2026-10-21_01'

# The local analysis environment has a damaged html standard-library module.
# Load the inspected, intact pure-Python module only for this process; do not
# modify any installed library, environment or experiment data.
clean_html=Path('C:/Users/30351/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/html/__init__.py')
spec=importlib.util.spec_from_file_location('html',clean_html,submodule_search_locations=[str(clean_html.parent)])
module=importlib.util.module_from_spec(spec);sys.modules['html']=module;spec.loader.exec_module(module)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

summary=json.loads((OUT/'heldout-summary.json').read_text('utf-8'))
guard=json.loads((OUT/'semantic-guard-summary.json').read_text('utf-8'))
labels=['Initial A','Initial B','Abstract repair','Witness repair','A + text guard*']
values=[summary['scores'][k] for k in ('A','B','abstract','witness')]+[guard['guardSuccess']]
primary=summary['primary']; secondary=guard['paired']
with plt.rc_context({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'}):
    fig,(ax,bx)=plt.subplots(1,2,figsize=(11,4.8),gridspec_kw={'width_ratios':[1.25,1]},layout='constrained')
    bars=ax.barh(labels,values,color=['#777777','#777777','#40576a','#0f766e','#777777'])
    ax.invert_yaxis();ax.set_xlim(0,60);ax.set_xlabel('Cases matching annotation (out of 60)');ax.set_ylabel('Method')
    ax.set_title('Feasible region AND optimal face')
    for bar,val in zip(bars,values):ax.text(val+0.5,bar.get_y()+bar.get_height()/2,str(val),va='center')
    for y,item,color in [(1,primary,'#0f766e'),(0,secondary,'#777777')]:
        center=item['difference']*100;lo,hi=[v*100 for v in item['pairedBootstrap95']]
        bx.errorbar(center,y,xerr=[[center-lo],[hi-center]],fmt='o',color=color,capsize=5)
    bx.axvline(0,color='#aaaaaa',linestyle='--',linewidth=1)
    bx.set_yticks([0,1],['Guard minus A*','Witness minus abstract'])
    bx.set_xlim(-10,7);bx.set_ylim(-.6,1.6);bx.set_xlabel('Paired change (percentage points)')
    bx.set_ylabel('Comparison');bx.set_title('95% paired bootstrap intervals')
    fig.suptitle('Public NL4Opt heldout cohort | 2026-10-21 | n = 60',fontsize=13)
    fig.text(.01,-.045,'*Exploratory guard. Fixed 10,000-draw bootstrap; no rescaling or exclusions. Official labels may be flawed.\nSource: heldout-summary.json and semantic-guard-summary.json. Publisher formatting not yet verified.',fontsize=8)
    for ext in ['png','svg','pdf']:fig.savefig(OUT/f'heldout-results.{ext}',dpi=200,bbox_inches='tight')
    plt.close(fig)
metadata={'matplotlib':matplotlib.__version__,'sources':['heldout-summary.json','semantic-guard-summary.json'],
          'population':60,'error_bars':'paired nonparametric bootstrap95%,10000 draws,seed20261021',
          'format_status':'Provisional general research figure; no publisher-compliance claim',
          'environment_workaround':'Process-local intact html module; installed environment unchanged'}
with (OUT/'figure-manifest.json').open('x',encoding='utf-8') as f:json.dump(metadata,f,indent=2)
print(json.dumps({'files':['heldout-results.png','heldout-results.svg','heldout-results.pdf']}))
