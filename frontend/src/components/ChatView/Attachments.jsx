import { getToken } from '../../api/client.js'

export default function Attachments({ attachments, chatId }) {
  if (!attachments || attachments.length === 0) return null
  const token = getToken()
  const images = attachments.filter(a => a.mime_type?.startsWith('image/'))
  const files = attachments.filter(a => !a.mime_type?.startsWith('image/'))

  return (
    <div className="chat__attachments">
      {images.length > 0 && (
        <div className="chat__attach-images">
          {images.map((img, i) => (
            <a
              key={i}
              href={`/api/chats/${chatId}/uploads/${img.name}?token=${token}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <img
                className="chat__attach-thumb"
                src={`/api/chats/${chatId}/uploads/${img.name}?token=${token}`}
                alt={img.name}
                loading="lazy"
              />
            </a>
          ))}
        </div>
      )}
      {files.map((f, i) => (
        <a
          key={i}
          className="chat__attach-file"
          href={`/api/chats/${chatId}/uploads/${f.name}?token=${token}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span className="chat__attach-file-name">{f.name}</span>
          <span className="chat__attach-file-size">{Math.round(f.size / 1024)}KB</span>
        </a>
      ))}
    </div>
  )
}
