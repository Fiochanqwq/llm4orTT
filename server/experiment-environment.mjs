import crypto from 'node:crypto';
export const environmentVersion='fixed-budget-environment-2';
const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function budgetIntent(question) {
  const text=String(question?.question??question??'').normalize('NFKC').trim();
  // Field/IDs alone are never authorization to disclose a private fact.
  const budget=/预算|经费|拨款|批准.{0,8}(?:钱|金额)|(?:可用|可动用).{0,6}(?:资金|金额)|\b(?:budget|funds?|funding|spending (?:cap|limit)|approved amount)\b/i.test(text);
  if(!budget)return 'unsupported';
  // This is a deliberately limited language adapter, not an oracle. Questions
  // about required costs, hypotheticals or mixed intents need human handling.
  // Check these BEFORE matching amount words ("how much", "至少", etc.).
  if(/最低|最少|最小|至少需要|需要多少|所需|满足.{0,12}(?:需求|要求)|\b(?:minimum|minimal|least|required|requirement|needed|need|meet|satisfy)\b/i.test(text.replace(/at least/gi,'')))return 'required_cost';
  if(/假设|假如|如果|若是|假定|suppos|hypothetic|\bif\b/i.test(text.replace(/tell me if/gi,'')))return 'ambiguous';
  if(/不要|不必|无需|不想|并非|不是|不问|\b(?:not|don't|do not|ignore|instead)\b/i.test(text.replace(/cannot be increased/gi,'')))return 'ambiguous';
  const increase=/(?:追加|增加|提高|放宽|更多|额外).{0,8}(?:预算|资金|经费|拨款)|(?:预算|经费).{0,10}(?:追加|增加|提高|放宽)|\b(?:increase|raise|extend|additional|extra|more)\b.{0,35}\b(?:budget|funds?|funding|cap)\b|\bbudget\b.{0,30}\b(?:increase|raise|extend|additional)\b/i.test(text.replace(/(?:不可|不能|不允许)追加(?:的)?|cannot be increased/gi,''));
  const actual=/(?:实际|具体|确切|已批准|确定|固定|可用).{0,12}(?:预算|资金|金额)|(?:预算|经费|拨款).{0,16}(?:多少|几|是多少|至少|达到|不低于|是否够|够不够)|批准.{0,8}(?:多少|几)|\b(?:actual|exact|approved|fixed|available)\b.{0,30}\b(?:budget|amount|funds?)\b|\b(?:what|how much)\b.{0,40}\b(?:budget|funds?|funding)\b|\bbudget\b.{0,35}(?:at least|above|below|enough|>=|≥|\?)/i.test(text);
  if(increase&&actual)return 'ambiguous';
  if(increase)return 'increase';
  if(/(?:原题|原始|给定|已知).{0,6}(?:区间|范围)|(?:预算|经费).{0,10}(?:区间|范围)|\b(?:range|interval)\b/i.test(text))return 'range';
  // Authorize complete direct questions, not a keyword substring in a request
  // to calculate a cost/shortfall. Unrecognized phrasing remains a human turn.
  const direct=text.replace(/可回答是\/否[，,]或填写实际预算[。.]?$|Answer yes\/no or enter the actual amount\.?$/i,'').trim().replace(/[?？。.!]+$/,'').trim();
  const zhSubject='(?:(?:当前|目前|实际|具体|确切|已|经|批准|确定|固定|可用|可动用|且|不可追加|不能追加|的|我们|你们|您|你|我)\\s*)*(?:预算|经费|拨款|资金)(?:总额|金额|额度)?';
  const enSubject='(?:(?:your|our|the|my|actual|exact|approved|fixed|available|total|current)\\s+)*(?:budget|funds?|funding|spending (?:cap|limit)|approved amount)';
  const amountQuestion=new RegExp(`^${zhSubject}(?:是多少|有多少|为多少|多少)$`).test(direct)
    ||new RegExp(`^(?:请|烦请|麻烦)?(?:提供|告知|确认|告诉我?|说明)${zhSubject}(?:是多少|有多少|为多少|多少)?$`).test(direct)
    ||/^(?:请)?(?:告诉我|告知|确认)?(?:实际|已)?批准了多少(?:钱|资金|经费)$/.test(direct)
    ||new RegExp(`^(?:what is|what's|how much is|(?:please )?(?:provide|tell me|specify|confirm)) ${enSubject}$`,'i').test(direct)
    ||/^how much (?:funding|funds?|budget) (?:has (?:actually )?been approved|is (?:actually )?available|do (?:we|you) have)$/i.test(direct);
  const amount='[0-9]+(?:[.,][0-9]+)*(?:/[0-9]+)?\\s*(?:USD|CNY|RMB|EUR|GBP|JPY|美元|元|欧元|英镑)?';
  const thresholdQuestion=new RegExp(`^${zhSubject}(?:(?:是否)?(?:至少为?|达到|不低于|不超过|低于|高于)|是否够)\\s*${amount}(?:[，,]?对吗)?$`,'i').test(direct)
    ||new RegExp(`^is ${enSubject} (?:at least|above|below|at most|no more than) ${amount}$`,'i').test(direct);
  return (actual||/资金/.test(direct))&&(amountQuestion||thresholdQuestion)?'amount':'ambiguous';
}
export function questionsFromText(content) {
  return String(content||'').split(/(?<=[?？。])|[\r\n]+/).map(s=>s.trim()).filter(s=>/[?？]$/.test(s)||/^(?:请|烦请|麻烦)(?:提供|告知|确认|告诉|说明)|^please\s+(?:provide|tell|specify|confirm)/i.test(s)).map(question=>({question}));
}
function cardUnit(card) {
  if(typeof card?.unit==='string'&&card.unit.trim())return card.unit.trim();
  const units=String(card?.oracle_reply||'').match(/美元|美金|人民币|欧元|英镑|日元|\b(?:USD|CNY|EUR|GBP|JPY)\b/gi)||[];
  return units.length===1?units[0]:null;
}
export function respondToQuestions(questions,card,{language='zh-CN'}={}) {
  const en=language==='en',amount=card?.hidden_fixed_budget??card?.budget,unit=cardUnit(card);
  const fixed=card?.confirmedFixed===true||Number.isFinite(card?.hidden_fixed_budget)||/固定|不可追加|不能追加|fixed|no additions/i.test(card?.oracle_reply||'');
  const decisions=(questions||[]).map(q=>{
    const intent=budgetIntent(q);let reply=null;
    if(intent==='amount'&&fixed&&Number.isFinite(amount)&&unit)reply=en?`Budget is ${amount} ${unit}; no additions.`:`已批准且固定的预算为 ${amount} ${unit}，不能追加。`;
    if(intent==='increase'&&fixed)reply=en?'The approved budget is fixed and cannot be increased.':'已批准预算固定，不能追加。';
    if(intent==='range'&&card?.publicBudgetRange&&Number.isFinite(card.publicBudgetRange.lower)&&Number.isFinite(card.publicBudgetRange.upper)&&unit)reply=`[${card.publicBudgetRange.lower}, ${card.publicBudgetRange.upper}] ${unit}`;
    return {question:q.question??String(q),intent,reply,disclosed:reply!==null,factKind:reply?intent:null};
  });
  const pending=decisions.filter(d=>!d.disclosed),replies=[...new Set(decisions.map(d=>d.reply).filter(Boolean))];
  return {version:environmentVersion,factHash:hash(card??null),decisions,reply:replies.length?replies.join('\n'):null,
    status:!decisions.length?'no_question':pending.length?'awaiting_human':'answered',unanswered:pending.map(d=>d.question)};
}
