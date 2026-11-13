/* Pure composition engine. Offsets use Unicode code points, as in Python. */
globalThis.SummaryComposer = (() => {
  const categories = ['predicate', 'entity', 'coreference'];
  const chars = text => Array.from(text);
  const overlap = (a, b, c, d) => a < d && c < b;
  const claimKey = row => row.claim_id || row.reference_claim_id || row.summary_sentence_id;

  function compose(rows, ids, documentId, category) {
    if (!categories.includes(category)) throw Error('Tipo de inconsistência inválido.');
    const lookup = new Map(rows.map(row => [row.injection_id, row]));
    if (lookup.size !== rows.length) throw Error('IDs de propostas repetidos.');
    const unique = new Set(ids);
    if (unique.size !== ids.length) throw Error('A mesma proposta foi selecionada duas vezes.');
    const chosen = ids.map(id => {
      const row = lookup.get(id);
      if (!row) throw Error('Proposta desconhecida: ' + id);
      if (row.document_id !== documentId) throw Error('Não combine propostas de documentos diferentes.');
      if (row.error_category !== category) throw Error('Não combine tipos diferentes no mesmo resumo.');
      return row;
    });
    if (!chosen.length) throw Error('Selecione pelo menos uma alteração deste tipo.');
    const original = chosen[0].original_summary_en;
    if (typeof original !== 'string' || !original) throw Error('Resumo original ausente.');
    const points = chars(original);
    const claimed = new Set();
    const hashes = new Set(chosen.map(row => row.generator?.source_sha256).filter(Boolean));
    if (hashes.size > 1) throw Error('As propostas pertencem a versões diferentes do documento.');
    for (const row of chosen) {
      if (row.original_summary_en !== original) throw Error('As propostas não compartilham o mesmo resumo original.');
      const claim = claimKey(row);
      if (!claim) throw Error('Identificação da claim ausente.');
      if (claimed.has(claim)) throw Error('Escolha somente uma alteração por claim dentro de cada tipo.');
      claimed.add(claim);
      const e = row.edit;
      if (!e || !Number.isInteger(e.start_char) || !Number.isInteger(e.end_char) ||
          e.start_char < 0 || e.start_char >= e.end_char || e.end_char > points.length ||
          typeof e.original !== 'string' || typeof e.replacement !== 'string') throw Error('Coordenadas de edição inválidas.');
      if (points.slice(e.start_char, e.end_char).join('') !== e.original) throw Error('O trecho original não coincide com a edição.');
      if (e.original === e.replacement) throw Error('A alteração não modifica o resumo.');
      if (row.modified_summary_en !== undefined &&
          points.slice(0,e.start_char).join('')+e.replacement+points.slice(e.end_char).join('') !== row.modified_summary_en)
        throw Error('A proposta contém alterações não descritas pela edição.');
      if (row.claim_token_spans?.length) {
        for (let p=e.start_char;p<e.end_char;p++) {
          if (!/\s/u.test(points[p]) && !row.claim_token_spans.some(s => s.start_char <= p && p < s.end_char))
            throw Error('A alteração ultrapassa a claim escolhida.');
        }
      }
      if ((row.other_claim_token_spans || []).some(s => overlap(e.start_char,e.end_char,s.start_char,s.end_char)))
        throw Error('A alteração afeta outra claim.');
    }
    const ordered = chosen.slice().sort((a,b) => a.edit.start_char-b.edit.start_char);
    for (let i=1;i<ordered.length;i++) {
      if (ordered[i].edit.start_char < ordered[i-1].edit.end_char)
        throw Error('As alterações selecionadas se sobrepõem. Remova uma delas.');
    }
    // A prior anaphor/antecedent may not be rewritten by another selected edit.
    for (const row of chosen) {
      if (row.error_category !== 'coreference') continue;
      const t = row.transformation_trace || {};
      for (const other of chosen) {
        if (other === row) continue;
        for (const span of [t.original_antecedent,t.wrong_antecedent]) {
          if (span && overlap(other.edit.start_char,other.edit.end_char,span.start_char,span.end_char))
            throw Error('Uma alteração reescreve o antecedente de outra correferência. Escolha outra combinação.');
        }
      }
    }
    let result = points.slice();
    for (const row of ordered.slice().reverse())
      result.splice(row.edit.start_char,row.edit.end_char-row.edit.start_char,...chars(row.edit.replacement));
    let shift=0;
    const edits=ordered.map(row => {
      const e=row.edit, start=e.start_char+shift;
      shift += chars(e.replacement).length-(e.end_char-e.start_char);
      return {injection_id:row.injection_id,claim_id:claimKey(row),summary_sentence_id:row.summary_sentence_id,
        strategy:row.strategy,original_start_char:e.start_char,original_end_char:e.end_char,
        modified_start_char:start,modified_end_char:start+chars(e.replacement).length,
        original:e.original,replacement:e.replacement,
        transformation_trace:row.transformation_trace || {}};
    });
    return {schema_version:'composed_summary_v1',document_id:documentId,error_category:category,
      inconsistency_count:chosen.length,edited_claims_count:claimed.size,
      selected_injection_ids:ordered.map(row=>row.injection_id),original_summary_en:original,
      modified_summary_en:result.join(''),edits,source_document_sha256:[...hashes][0] || null,
      human_selected:true,human_validated_modified_relation:false,gold_eligible:false,
      hypothesized_modified_relation:'UNKNOWN',validation_status:'COMPOSED_PROPOSALS_NOT_FACTUALLY_VALIDATED'};
  }
  function forType(rows, selection, documentId, category) {
    const selected = selection instanceof Set ? selection : new Set(selection);
    return rows.filter(row => selected.has(row.injection_id) && row.document_id === documentId && row.error_category === category)
      .map(row => row.injection_id);
  }
  function validateSelection(rows, ids) {
    if (!Array.isArray(ids) || ids.some(id=>typeof id!=='string')) throw Error('Seleção inválida.');
    const lookup=new Map(rows.map(row=>[row.injection_id,row]));
    const groups=new Map();
    for (const id of ids) {
      const row=lookup.get(id);
      if (!row) throw Error('Proposta desconhecida: '+id);
      const key=JSON.stringify([row.document_id,row.error_category]);
      if (!groups.has(key)) groups.set(key,[]);
      groups.get(key).push(id);
    }
    for (const ids of groups.values()) {
      const row=lookup.get(ids[0]);compose(rows,ids,row.document_id,row.error_category);
    }
    return new Set(ids);
  }
  return {compose, forType, validateSelection, claimKey, categories};
})();
