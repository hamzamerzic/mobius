import { StandardMarkdown } from './markdown/BlockRenderer.jsx'
import ToolBlock from './ToolBlock.jsx'
import Attachments from './Attachments.jsx'


function stripAugmentation(text) {
  let cleaned = text.replace(/\s*<agent_experience>[\s\S]*?<\/agent_experience>\s*/g, '')
  cleaned = cleaned.replace(/\s*\[Files in this session:\n[\s\S]*?\]\s*/g, '')
  return cleaned.trim()
}


export default function MsgContent({ msg, chatId }) {
  if (msg.blocks && msg.blocks.length > 0) {
    return (
      <>
        {msg.role === 'user' && <Attachments attachments={msg.attachments} chatId={chatId} />}
        {msg.blocks.map((block, i) => {
          if (block.type === 'text') {
            const text = msg.role === 'user'
              ? stripAugmentation(block.content) : block.content
            if (!text) return null
            return (
              <div key={i} className={`chat__text chat__text--${msg.role}`}>
                {msg.role === 'assistant'
                  ? <StandardMarkdown text={text} />
                  : text}
              </div>
            )
          }
          if (block.type === 'tool') {
            return (
              <div key={i} className="chat__tools">
                <ToolBlock t={block} />
              </div>
            )
          }
          return null
        })}
      </>
    )
  }

  const text = msg.role === 'user' && msg.content
    ? stripAugmentation(msg.content) : msg.content

  return (
    <>
      {msg.role === 'user' && <Attachments attachments={msg.attachments} chatId={chatId} />}
      {text ? (
        <div className={`chat__text chat__text--${msg.role}`}>
          {msg.role === 'assistant'
            ? <StandardMarkdown text={text} />
            : text}
        </div>
      ) : null}
    </>
  )
}
