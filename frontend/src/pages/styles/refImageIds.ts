/**
 * Parse a comma-separated list of reference-image IDs (opaque numeric IDs —
 * never a content hash/SHA) into an int array, mirroring the legacy HTML
 * form's server-side parser (app/routes/styles.py::_parse_ref_image_ids) so
 * client and server agree on the accepted shape. Throws with a
 * user-readable message on anything that isn't a comma-separated list of
 * integers.
 *
 * Kept in its own non-component module (rather than inside
 * StyleFormPage.tsx) so that file stays component-only for the
 * react(only-export-components) fast-refresh lint rule.
 */
export function parseRefImageIds(raw: string): number[] {
  const ids: number[] = []
  for (const part of raw.split(',')) {
    const trimmed = part.trim()
    if (!trimmed) continue
    if (!/^-?\d+$/.test(trimmed)) {
      throw new Error(`Reference image IDs must be comma-separated integers, got "${trimmed}"`)
    }
    ids.push(Number(trimmed))
  }
  return ids
}
