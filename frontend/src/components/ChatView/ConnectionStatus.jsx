/**
 * Subtle reconnection indicator shown when the SSE connection is lost.
 */
export default function ConnectionStatus({ error, onRetry }) {
  if (!error) return null

  return (
    <div className="connection-status">
      {error === 'retrying' ? (
        <span className="connection-status__text">Reconnecting...</span>
      ) : (
        <>
          <span className="connection-status__text">Connection lost</span>
          <button className="connection-status__retry" onClick={onRetry}>
            Retry
          </button>
        </>
      )}
    </div>
  )
}
