import './MenuButton.css'

export default function MenuButton({ onClick }) {
  return (
    <button
      className="menu-btn"
      onClick={onClick}
      aria-label="Open menu"
    >
      <span className="menu-btn__bar" />
      <span className="menu-btn__bar" />
      <span className="menu-btn__bar" />
    </button>
  )
}
