import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  /** 助手正文按 Markdown 渲染（LLM 输出不可信，统一经 rehype-sanitize 净化）；用户气泡纯文本 */
  markdown?: boolean;
}

/** 聊天气泡：用户纯文本 pre-wrap；助手支持 Markdown（GFM 表格/代码 + XSS 净化）。 */
export default function ChatBubble({ role, content, markdown = false }: Props) {
  const isUser = role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        margin: '8px 0',
      }}
    >
      <div
        style={{
          maxWidth: '78%',
          padding: '8px 12px',
          borderRadius: 8,
          whiteSpace: markdown ? 'normal' : 'pre-wrap',
          wordBreak: 'break-word',
          background: isUser ? '#1677ff' : '#f0f0f0',
          color: isUser ? '#fff' : 'rgba(0,0,0,0.88)',
        }}
      >
        {markdown ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
            {content}
          </ReactMarkdown>
        ) : (
          content
        )}
      </div>
    </div>
  );
}
