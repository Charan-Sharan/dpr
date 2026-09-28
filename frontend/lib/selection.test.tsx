import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { Markdown } from '@/components/Markdown'
import { markdownSelection } from './selection'

afterEach(cleanup)
function select(
  markdown: string,
  first: string,
  last = first,
  firstOffset = 0,
  lastOffset = last.length,
  occurrence = 0,
) {
  const { container } = render(
    <div className="markdown-block">
      <Markdown text={markdown} />
    </div>,
  )
  const block = container.firstChild as HTMLElement
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  const start = nodes.filter((node) => node.data === first)[occurrence]
  const end = first === last ? start : nodes.find((node) => node.data === last)!
  const range = document.createRange()
  range.setStart(start, firstOffset)
  range.setEnd(end, lastOffset)
  return markdownSelection(block, range, markdown)
}

describe('Markdown passage selection', () => {
  it('maps repeated phrases by their document position', () => {
    expect(
      select('Same phrase.\n\nSame phrase.', 'Same phrase.', 'Same phrase.', 0, 12, 1),
    ).toEqual({ text: 'Same phrase.', start: 14, end: 26 })
    expect(select('**Same** *Same*', 'Same', 'Same', 0, 4, 1)).toEqual({
      text: '*Same*',
      start: 9,
      end: 15,
    })
  })
  it('selects across formatting and preserves the complete inline markup', () => {
    expect(select('Write **careful** prose.', 'Write ', ' prose.')).toEqual({
      text: 'Write **careful** prose.',
      start: 0,
      end: 24,
    })
    expect(select('Write **careful** prose.', 'Write ', 'careful')).toEqual({
      text: 'Write **careful**',
      start: 0,
      end: 17,
    })
  })
  it('selects part of formatted text without including its delimiters', () => {
    expect(select('Write **careful** prose.', 'careful', 'careful', 1, 5)).toEqual({
      text: 'aref',
      start: 9,
      end: 13,
    })
  })
  it('maps escaped punctuation and HTML entities to their source', () => {
    expect(select('A &amp; B \\* C', 'A & B * C', 'A & B * C', 2, 7)).toEqual({
      text: '&amp; B \\*',
      start: 2,
      end: 12,
    })
  })
  it('uses Python character offsets for emoji before a passage', () => {
    expect(select('😀 Same **Same**', 'Same', 'Same', 0, 2)).toEqual({
      text: 'Sa',
      start: 9,
      end: 11,
    })
  })
  it('maps inline and fenced code content', () => {
    expect(select('Try `a  b` now.', 'a  b', 'a  b', 0, 1)).toEqual({ text: 'a', start: 5, end: 6 })
    expect(select('```js\nhello\n```', 'hello\n', 'hello\n', 1, 4)).toEqual({
      text: 'ell',
      start: 7,
      end: 10,
    })
  })
  it('handles range boundaries on elements', () => {
    const markdown = 'Write **careful** prose.'
    const { container } = render(
      <div>
        <Markdown text={markdown} />
      </div>,
    )
    const block = container.firstChild as HTMLElement
    const range = document.createRange()
    range.selectNodeContents(block.querySelector('p')!)
    expect(markdownSelection(block, range, markdown)?.text).toBe(markdown)
  })
  it('includes fully selected links and keeps partial link selections precise', () => {
    expect(select('Read [the guide](https://example.com) today.', 'Read ', 'the guide')).toEqual({
      text: 'Read [the guide](https://example.com)',
      start: 0,
      end: 37,
    })
    expect(
      select('Read [the guide](https://example.com) today.', 'the guide', 'the guide', 4, 9),
    ).toEqual({
      text: 'guide',
      start: 10,
      end: 15,
    })
  })
})
