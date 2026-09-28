import { memo } from 'react'
import type { Paper, Source } from '@/types'
import { Markdown } from './Markdown'

export const Document = memo(function Document({
  paper,
  sources,
  capture,
}: {
  paper: Paper
  sources: Source[]
  capture: () => void
}) {
  return (
    <article id="paper" aria-label="Latest document" onMouseUp={capture} onKeyUp={capture}>
      <h1>{paper.title}</h1>
      {paper.sections.map((section) => (
        <section id={section.id} key={section.id}>
          {section.heading && <h2>{section.heading}</h2>}
          {section.blocks.map((block) => (
            <div key={block.id}>
              <div className="markdown-block" data-section-id={section.id} data-block-id={block.id}>
                <Markdown text={block.text} />
              </div>
              {!!block.claims?.length && (
                <div className="cite">
                  Sources:{' '}
                  {[
                    ...new Set(
                      block.claims.flatMap((claim) =>
                        (claim.citations || []).map(
                          (citation) =>
                            sources.find((source) => source.id === citation.source_id)?.title ||
                            citation.source_id,
                        ),
                      ),
                    ),
                  ].join('; ')}
                </div>
              )}
            </div>
          ))}
        </section>
      ))}
      {!paper.sections.length && (
        <div className="empty-state">
          <p>Your document is empty.</p>
          <p>Describe what you want to write below, or use Edit Markdown to paste a draft.</p>
        </div>
      )}
    </article>
  )
})
