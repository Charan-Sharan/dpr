// Local, DOM-only Markdown renderer. Raw HTML is displayed as text, never executed.
// Supported: headings, paragraphs, emphasis, links, code, lists, quotes and tables.
function markdownInline(text, target) {
  const pattern = /(`+)([^`]+)\1|\[([^\]]+)\]\(([^\s)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\n]+)\*|_([^_\n]+)_|~~([^~]+)~~/g;
  let last = 0, match;
  while ((match = pattern.exec(text))) {
    target.append(document.createTextNode(text.slice(last, match.index)));
    let node;
    if (match[1]) { node = document.createElement('code'); node.textContent = match[2]; }
    else if (match[3]) {
      node = document.createElement('a'); node.textContent = match[3];
      if (/^(https?:\/\/|mailto:|#)/i.test(match[4])) {
        node.href = match[4]; node.rel = 'noopener noreferrer';
        if (!match[4].startsWith('#')) node.target = '_blank';
      }
    } else {
      node = document.createElement(match[5] || match[6] ? 'strong' : match[9] ? 'del' : 'em');
      node.textContent = match[5] || match[6] || match[7] || match[8] || match[9];
    }
    target.append(node); last = pattern.lastIndex;
  }
  target.append(document.createTextNode(text.slice(last)));
}
function renderMarkdown(text, depth = 0) {
  const root = document.createDocumentFragment(), lines = text.replace(/\r\n?/g, '\n').split('\n');
  const tableCells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim());
  const tableRule = line => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line || '');
  const blockStart = line => /^\s*$|^ {0,3}(#{1,6}\s|`{3,}|~{3,}|>\s?|[-+*]\s+|\d+[.)]\s+|(?:-\s*){3,}$|(?:\*\s*){3,}$)/.test(line);
  for (let i = 0; i < lines.length;) {
    const line = lines[i]; let match;
    if (!line.trim()) { i++; continue; }
    if ((match = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/))) {
      const pre = document.createElement('pre'), code = document.createElement('code'), body = [];
      const closing = new RegExp('^ {0,3}' + match[1][0] + '{' + match[1].length + ',}\\s*$');
      i++; while (i < lines.length && !closing.test(lines[i])) body.push(lines[i++]);
      if (i < lines.length) i++;
      code.textContent = body.join('\n'); pre.append(code); root.append(pre); continue;
    }
    if ((match = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*$/))) {
      const h = document.createElement('h' + match[1].length); markdownInline(match[2], h); root.append(h); i++; continue;
    }
    if (/^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)) { root.append(document.createElement('hr')); i++; continue; }
    if (/^ {0,3}>/.test(line) && depth < 10) {
      const quote = document.createElement('blockquote'), body = [];
      while (i < lines.length && /^ {0,3}>/.test(lines[i])) body.push(lines[i++].replace(/^ {0,3}> ?/, ''));
      quote.append(renderMarkdown(body.join('\n'), depth + 1)); root.append(quote); continue;
    }
    if ((match = line.match(/^ {0,3}([-+*]|\d+[.)])\s+(.*)$/))) {
      const ordered = /^\d/.test(match[1]), list = document.createElement(ordered ? 'ol' : 'ul');
      if (ordered) list.start = parseInt(match[1], 10);
      while (i < lines.length) {
        const item = lines[i].match(/^ {0,3}([-+*]|\d+[.)])\s+(.*)$/);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        const li = document.createElement('li'); markdownInline(item[2], li); list.append(li); i++;
      }
      root.append(list); continue;
    }
    if (line.includes('|') && tableRule(lines[i + 1])) {
      const wrap = document.createElement('div'), table = document.createElement('table'), head = document.createElement('thead'), body = document.createElement('tbody');
      wrap.className = 'table-scroll';
      const row = (values, tag) => { const tr = document.createElement('tr'); values.forEach(value => { const cell = document.createElement(tag); markdownInline(value, cell); tr.append(cell); }); return tr; };
      head.append(row(tableCells(line), 'th')); i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) body.append(row(tableCells(lines[i++]), 'td'));
      table.append(head, body); wrap.append(table); root.append(wrap); continue;
    }
    const paragraph = [line]; i++;
    while (i < lines.length && !blockStart(lines[i]) && !tableRule(lines[i + 1])) paragraph.push(lines[i++]);
    const p = document.createElement('p'); markdownInline(paragraph.join('\n'), p); root.append(p);
  }
  return root;
}
