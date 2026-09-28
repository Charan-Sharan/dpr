import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { selectionPositions } from '@/lib/selection'

// React escapes raw HTML; restrict links to the protocols supported by the old renderer.
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[selectionPositions]}
      urlTransform={(url) => (/^(https?:\/\/|mailto:|#)/i.test(url) ? url : '')}
      components={{
        a: ({ href, children, node: _node, ...props }) => (
          <a
            {...props}
            href={href || undefined}
            target={href && !href.startsWith('#') ? '_blank' : undefined}
            rel="noopener noreferrer"
          >
            {children}
          </a>
        ),
        img: ({ alt }) => <span>{alt}</span>,
        table: ({ children }) => (
          <div className="table-scroll">
            <table>{children}</table>
          </div>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  )
})
