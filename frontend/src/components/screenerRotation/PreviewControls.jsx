export function PreviewControls({ preview, itemLabel = 'rows', onModeChange }) {
  if (!preview) return null
  if (!preview.canShowMore && !preview.canShowAll && !preview.canCollapse) return null

  return (
    <div className="section-controls">
      <span className="section-controls-note">
        {preview.mode === 'all'
          ? `Showing all ${preview.total} ${itemLabel}.`
          : `Showing ${preview.shownCount} of ${preview.total} ${itemLabel}.`}
      </span>
      <div className="section-controls-actions">
        {preview.canShowMore && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('more')}
          >
            Show more
          </button>
        )}
        {preview.canShowAll && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('all')}
          >
            Show all
          </button>
        )}
        {preview.canCollapse && (
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => onModeChange('preview')}
          >
            Collapse
          </button>
        )}
      </div>
    </div>
  )
}

export function PreviewGapRow({ colSpan, hiddenCount }) {
  return (
    <tr>
      <td colSpan={colSpan} className="preview-gap-cell">
        ... {hiddenCount} row{hiddenCount !== 1 ? 's' : ''} hidden ...
      </td>
    </tr>
  )
}

export function ExportButton({ onClick, disabled = false }) {
  return (
    <button
      type="button"
      className="btn btn-secondary btn-compact"
      onClick={onClick}
      disabled={disabled}
    >
      Export CSV
    </button>
  )
}
