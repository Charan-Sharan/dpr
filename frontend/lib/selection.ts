import type { Element, Root, RootContent } from 'hast'

// Keep parser positions beside rendered text, rather than searching the document
// for a phrase that may occur more than once or contain invisible Markdown.
export function selectionPositions() {
  return (tree: Root) => {
    function visit(parent: Root | Element) {
      parent.children = parent.children.map((node): RootContent => {
        if (node.type === 'element') {
          const start = node.position?.start.offset,
            end = node.position?.end.offset
          if (start !== undefined && end !== undefined) {
            node.properties['data-markdown-start'] = start
            node.properties['data-markdown-end'] = end
          }
          visit(node)
        } else if (node.type === 'text') {
          const position =
            node.position ||
            (parent.type === 'element' && parent.tagName === 'code' ? parent.position : undefined)
          const start = position?.start.offset,
            end = position?.end.offset
          if (start !== undefined && end !== undefined) {
            return {
              type: 'element',
              tagName: 'span',
              properties: {
                'data-source-start': start,
                'data-source-end': end,
                'data-source-kind':
                  parent.type === 'element' && parent.tagName === 'code' ? 'code' : 'text',
              },
              children: [node],
            }
          }
        }
        return node
      })
    }
    visit(tree)
  }
}

function offsets(raw: string, visible: string, base: number, code: boolean) {
  let from = 0,
    to = raw.length
  if (code) {
    const fence = raw.match(/^ {0,3}(`{3,}|~{3,})[^\r\n]*\r?\n/)
    if (fence) {
      from = fence[0].length
      const closing = raw.slice(from).match(/(?:^|\n) {0,3}(?:`{3,}|~{3,})\s*$/)
      if (closing) to = from + closing.index! + (closing[0].startsWith('\n') ? 1 : 0)
    } else {
      const ticks = raw.match(/^`+/)
      if (ticks) {
        from = ticks[0].length
        to -= ticks[0].length
        const content = raw.slice(from, to).replace(/\r?\n/g, ' ')
        if (content.startsWith(' ') && content.endsWith(' ') && /[^ ]/.test(content)) {
          from++
          to--
        }
      }
    }
  }
  const tokens: { value: string; start: number; end: number }[] = []
  const decoder = document.createElement('textarea')
  for (let index = from; index < to;) {
    let length = 1,
      value = raw[index]
    if (
      !code &&
      raw[index] === '\\' &&
      /[!"#$%&'()*+,\-./:;<=>?@[\]\\^_`{|}~]/.test(raw[index + 1] || '')
    ) {
      length = 2
      value = raw[index + 1]
    } else if (!code && raw[index] === '&') {
      const entity = raw.slice(index).match(/^&(?:#[xX][\da-fA-F]+|#\d+|[a-zA-Z][\da-zA-Z]*);/)
      if (entity) {
        decoder.innerHTML = entity[0]
        if (decoder.value !== entity[0]) {
          length = entity[0].length
          value = decoder.value
        }
      }
    } else if (raw[index] === '\r' && raw[index + 1] === '\n') {
      length = 2
      value = '\n'
    }
    if (code && raw.startsWith('`') && value === '\n') value = ' '
    for (const unit of value.split(''))
      tokens.push({ value: unit, start: base + index, end: base + index + length })
    index += length
  }
  const mapped: typeof tokens = []
  let cursor = 0
  for (const unit of visible.split('')) {
    while (tokens[cursor] && tokens[cursor].value !== unit && /\s/.test(tokens[cursor].value))
      cursor++
    if (!tokens[cursor]) {
      // Fenced code rendering can append a final newline absent in the source.
      if (unit === '\n' && mapped.length) {
        mapped.push({ value: unit, start: base + to, end: base + to })
        continue
      }
      return null
    }
    if (tokens[cursor].value !== unit) return null
    mapped.push(tokens[cursor++])
  }
  return mapped
}

export function markdownSelection(block: HTMLElement, range: Range, markdown: string) {
  const spans = [...block.querySelectorAll<HTMLElement>('[data-source-start]')]
  let start: number | undefined, end: number | undefined
  for (const span of spans) {
    const node = span.firstChild
    if (!node || node.nodeType !== Node.TEXT_NODE || !range.intersectsNode(node)) continue
    const content = block.ownerDocument.createRange()
    content.selectNodeContents(node)
    if (
      range.compareBoundaryPoints(Range.END_TO_START, content) >= 0 ||
      range.compareBoundaryPoints(Range.START_TO_END, content) <= 0
    )
      continue
    const low = range.startContainer === node ? range.startOffset : 0
    const high = range.endContainer === node ? range.endOffset : node.textContent!.length
    if (low >= high) continue
    const base = Number(span.dataset.sourceStart),
      limit = Number(span.dataset.sourceEnd)
    const map = offsets(
      markdown.slice(base, limit),
      node.textContent || '',
      base,
      span.dataset.sourceKind === 'code',
    )
    if (!map) return null
    start ??= map[low].start
    end = map[high - 1].end
  }
  if (start === undefined || end === undefined || start >= end) return null
  // Include delimiters for inline formatting fully covered by the selection.
  // Partial selections inside an inline element retain its surrounding markup.
  for (const element of block.querySelectorAll<HTMLElement>('strong, em, del, a, code')) {
    const walker = block.ownerDocument.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    const texts: Text[] = []
    while (walker.nextNode()) texts.push(walker.currentNode as Text)
    if (!texts.length) continue
    const content = block.ownerDocument.createRange()
    content.setStart(texts[0], 0)
    content.setEnd(texts[texts.length - 1], texts[texts.length - 1].length)
    if (
      range.compareBoundaryPoints(Range.START_TO_START, content) <= 0 &&
      range.compareBoundaryPoints(Range.END_TO_END, content) >= 0
    ) {
      if (element.dataset.markdownStart !== undefined)
        start = Math.min(start, Number(element.dataset.markdownStart))
      if (element.dataset.markdownEnd !== undefined)
        end = Math.max(end, Number(element.dataset.markdownEnd))
    }
  }
  return {
    text: markdown.slice(start, end),
    start: Array.from(markdown.slice(0, start)).length,
    end: Array.from(markdown.slice(0, end)).length,
  }
}
