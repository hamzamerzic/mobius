export const RECOVERY_CONTROL_URL = 'https://www.mobius.you/'

/** Recovery is external, so nested errors must navigate the top-level control plane. */
export default function RecoveryLink({
  className = 'errbound__recovery',
  lead = 'If the problem continues after trying again,',
}) {
  return (
    <p className={className}>
      {lead}{' '}
      <a href={RECOVERY_CONTROL_URL} target="_top">open Recovery in mobius.you</a>.
      {' '}Self-hosted: run <code>mobiusctl recovery start</code>.
    </p>
  )
}
