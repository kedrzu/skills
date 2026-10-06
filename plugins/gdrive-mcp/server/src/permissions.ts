// What a project lets the agent do in Drive. Five switches, each covering a set of tools.
//
// The OAuth scope is the full `drive` scope, because one token serves every project that
// uses the account. The switches are enforced here instead: a tool whose permission is
// off is neither listed nor executed.

export const PERMISSIONS = ["browse", "download", "upload", "edit", "delete"] as const;
export type Permission = (typeof PERMISSIONS)[number];
export type Permissions = Record<Permission, boolean>;
export type PermissionsConfig = Partial<Permissions>;

// Reading is on unless a project turns it off; anything that writes is opt-in.
export const DEFAULT_PERMISSIONS: Permissions = {
  browse: true,
  download: true,
  upload: false,
  edit: false,
  delete: false,
};

export const PERMISSION_DESCRIPTIONS: Record<Permission, string> = {
  browse: "search, list folders and shared drives, read file metadata",
  download: "read file contents and save files locally",
  upload: "create files and folders",
  edit: "replace file contents, rename, move, change descriptions and stars",
  delete: "move files to the trash and restore them (never permanent deletion)",
};

// The permission each tool needs; null means always available.
export const TOOL_PERMISSION: Record<string, Permission | null> = {
  list_accounts: null,
  search_files: "browse",
  list_folder: "browse",
  get_file_info: "browse",
  list_shared_drives: "browse",
  read_file: "download",
  download_file: "download",
  upload_file: "upload",
  create_folder: "upload",
  update_file: "edit",
  update_file_metadata: "edit",
  trash_file: "delete",
  restore_file: "delete",
};

export class PermissionDenied extends Error {}

export function effectivePermissions(config?: PermissionsConfig): Permissions {
  return { ...DEFAULT_PERMISSIONS, ...config };
}

export function validatePermissions(raw: unknown): string[] {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return [`expected an object of ${PERMISSIONS.join(", ")} set to true or false`];
  }
  const errors: string[] = [];
  for (const [key, value] of Object.entries(raw)) {
    if (!(PERMISSIONS as readonly string[]).includes(key)) {
      errors.push(`${key}: unknown permission (known: ${PERMISSIONS.join(", ")})`);
    } else if (typeof value !== "boolean") {
      errors.push(`${key}: expected true or false`);
    }
  }
  return errors;
}

// Throws when the project does not allow the tool. Unknown tools pass through, so the
// dispatcher reports them as unknown.
export function assertAllowed(tool: string, permissions: Permissions, configFile: string): void {
  const needed = TOOL_PERMISSION[tool];
  if (!needed || permissions[needed]) return;
  throw new PermissionDenied(
    `${tool} needs the '${needed}' permission (${PERMISSION_DESCRIPTIONS[needed]}), which this project does not grant. ` +
      `Only the user can turn it on, with "permissions": { "${needed}": true } in ${configFile}.`
  );
}
