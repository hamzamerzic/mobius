/* Decides when the interactive composer must ask for an explicit model. */

export function needsModelSelection({ showPicker, chatInfo }) {
  if (!showPicker) return false
  return !chatInfo?.effective?.model
}
