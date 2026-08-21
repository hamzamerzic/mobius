import ProjectCreateMenu from './ProjectCreateMenu.jsx'
import ProjectTypeIcon from './ProjectTypeIcon.jsx'
import './Projects.css'

// The Projects launcher: one clean list of the owner's projects plus the create
// menu. The icon/list view toggle and the legacy "Existing app projects" import
// section were removed — a single readable list is the one good default, and
// legacy app-projects are no longer surfaced here.
export default function ProjectsDirectory({
  projects,
  templates,
  status,
  onRetry,
  onOpen,
  onCreate,
}) {
  return (
    <section className="projects-directory" aria-label="Projects">
      <header className="projects-directory__header">
        <div>
          <h1>Projects</h1>
          <p>Your files, artifacts, and project chats.</p>
        </div>
        <div className="projects-directory__actions">
          <ProjectCreateMenu templates={templates} onCreate={onCreate} className="projects-add-menu" />
        </div>
      </header>
      <div className="projects-directory__scroll">
        {status === 'loading' ? (
          <p className="projects-empty" role="status">Loading projects…</p>
        ) : status === 'error' ? (
          <div className="projects-empty" role="alert">
            <p>Projects are unavailable.</p>
            <button type="button" onClick={onRetry}>Try again</button>
          </div>
        ) : projects.length === 0 ? (
          <div className="projects-empty">
            <ProjectTypeIcon value="blank" size={42} strokeWidth={1.4} aria-hidden="true" />
            <p>No projects yet.</p>
            <button type="button" onClick={() => onCreate?.(templates[0] || { key: 'blank', name: 'Blank project' })}>Create a project</button>
          </div>
        ) : (
          <div className="projects-collection projects-collection--list">
            {projects.map(project => (
              <button key={project.id} type="button" onClick={() => onOpen(project)}>
                <span className="projects-collection__icon" aria-hidden="true"><ProjectTypeIcon value={project} size={22} /></span>
                <span className="projects-collection__copy">
                  <strong>{project.name}</strong>
                  <small>{project.template?.name || project.project_type}</small>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
