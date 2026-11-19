// Schema version of the JSON files the CLI writes in build/ (the "schema" field;
// those from before 0.7.0 do not have it). The extension reads up to this version:
// given a newer one it warns and does not use the file, rather than misreading it.

export const SUPPORTED_SCHEMA = 1;

/** Message if the file uses a schema this version does not understand. */
export function schemaProblem(data: { schema?: unknown; cobalto?: unknown }, file: string): string | undefined {
  if (typeof data.schema === 'number' && data.schema > SUPPORTED_SCHEMA) {
    return `${file}: schema ${data.schema} from Cobalto ${String(data.cobalto ?? '?')}; this extension reads up to schema ${SUPPORTED_SCHEMA}. Update the extension.`;
  }
  return undefined;
}
