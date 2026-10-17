// Small continuous LP certificate. All arithmetic below is exact BigInt rational.
// Unsupported dimensions/domains or reconstruction failures return null, never a proof.
const gcd=(a,b)=>{a=a<0n?-a:a;b=b<0n?-b:b;while(b){[a,b]=[b,a%b];}return a||1n;};
function r(n,d=1n){if(d===0n)throw Error('zero denominator');if(d<0n){n=-n;d=-d;}const g=gcd(n,d);return {n:n/g,d:d/g};}
const add=(a,b)=>r(a.n*b.d+b.n*a.d,a.d*b.d), neg=a=>r(-a.n,a.d), sub=(a,b)=>add(a,neg(b)), mul=(a,b)=>r(a.n*b.n,a.d*b.d), div=(a,b)=>r(a.n*b.d,a.d*b.n), cmp=(a,b)=>{const n=a.n*b.d-b.n*a.d;return n<0n?-1:n>0n?1:0;};
const zero=r(0n), str=a=>a.d===1n?String(a.n):`${a.n}/${a.d}`;
function decimal(x){if(!Number.isFinite(x))throw Error('nonfinite');const [base,e='0']=String(x).toLowerCase().split('e');const digits=base.replace('.',''),scale=(base.split('.')[1]?.length||0)-Number(e);return scale>=0?r(BigInt(digits),10n**BigInt(scale)):r(BigInt(digits)*10n**BigInt(-scale));}
function fraction(x){const sign=x<0?-1n:1n;let t=Math.abs(x),a0=0n,a1=1n,b0=1n,b1=0n;for(let i=0;i<30;i++){const q=BigInt(Math.floor(t)),a=q*a1+a0,b=q*b1+b0;if(b>1000000n)break;if(Math.abs(Number(a)/Number(b)-Math.abs(x))<1e-10)return r(sign*a,b);[a0,a1,b0,b1]=[a1,a,b1,b];const rem=t-Math.floor(t);if(!rem)break;t=1/rem;}return decimal(x);}
const dot=(a,b)=>a.reduce((s,v,i)=>add(s,mul(v,b[i])),zero);
export function exactCertificate(model, values) {
  try {
    if(!values||model.sense!=='minimize'||model.variables.length>2||model.variables.some(v=>v.type!=='continuous'))return null;
    const names=model.variables.map(v=>v.name),x=names.map(k=>fraction(values[k])),c=names.map(k=>decimal(model.objective[k]||0)),rows=[];
    for(const row of model.constraints){const a=names.map(k=>decimal(row.terms[k]||0)),b=decimal(row.rhs);if(row.sense!== '<=')rows.push({a,b});if(row.sense!== '>=')rows.push({a:a.map(neg),b:neg(b)});}
    for(const [i,v] of model.variables.entries())for(const [bound,sign] of [[v.lower,1],[v.upper,-1]])if(bound!==null)rows.push({a:names.map((_,j)=>decimal(i===j?sign:0)),b:decimal(sign*bound)});
    if(rows.some(row=>cmp(dot(row.a,x),row.b)<0))return null;
    const active=rows.filter(row=>cmp(dot(row.a,x),row.b)===0),candidates=[];
    if(names.length===1){for(const a of active)if(a.a[0].n)candidates.push({rows:[a],y:[div(c[0],a.a[0])]});}
    else {let examined=0;pairs:for(let i=0;i<active.length;i++)for(let j=i+1;j<active.length;j++){
      if(++examined>4096)break pairs; // Bounded certificate search; exhaustion is uncertainty.
      const a=active[i],b=active[j],det=sub(mul(a.a[0],b.a[1]),mul(b.a[0],a.a[1]));if(!det.n)continue;
      candidates.push({rows:[a,b],y:[div(sub(mul(c[0],b.a[1]),mul(b.a[0],c[1])),det),div(sub(mul(a.a[0],c[1]),mul(c[0],a.a[1])),det)]});
    }}
    const objective=dot(c,x);
    const proof=candidates.find(p=>p.y.every(y=>cmp(y,zero)>=0)&&names.every((_,i)=>cmp(dot(p.rows.map(row=>row.a[i]),p.y),c[i])===0)&&cmp(dot(p.rows.map(row=>row.b),p.y),objective)===0);
    if(!proof)return null;
    return {format:'llm4orovo.rational-lp-certificate.v1',objective:str(objective),values:Object.fromEntries(names.map((k,i)=>[k,str(x[i])])),dual:proof.rows.map((row,i)=>({coefficients:row.a.map(str),rhs:str(row.b),multiplier:str(proof.y[i])})),scope:'continuous LP with at most two variables'};
  }catch{return null;}
}
export function compareExact(text,value){const [n,d='1']=text.split('/');return cmp(r(BigInt(n),BigInt(d)),decimal(value));}
