# Version management

The `VERSION` file and `CHANGELOG.md` describe the checked-in product state. A Git tag identifies an immutable source snapshot; a GitHub Release is a separate distribution artifact.

## Version stages

| Example | Meaning |
| --- | --- |
| `0.1.0-prototype.1` | Current UI prototype; not an installable app |
| `0.1.0-alpha.1` | First actual installable private test build, after it passes installation checks |
| `0.1.0-alpha.2` | A subsequent private test build |
| `0.1.0` | A deliberately approved non-prerelease version |
| `0.2.0` | A subsequent capability release |

These later versions are examples, not releases already created. Public visibility and version maturity are independent: an alpha can remain private, and a private repository does not automatically become public at version 0.1.0.

## Development workflow

- Keep the repository's default branch as the shared baseline. Use `codex/<change>` branches for implementation work.
- Make focused commits with a concise explanation of the change; update the changelog for user-visible behavior.
- Use pull requests for subsequent changes and run checks appropriate to the changed behavior before merging.
- Create annotated `v<VERSION>` tags for deliberate milestones. Never move a published version tag or replace release assets under the same version; issue a new version for fixes.
- Do not create a downloadable app release for a prototype-only tag.

## Before publishing an installable private build

1. Build the app and helper, and verify that their reported version matches `VERSION`.
2. Test installation, launch, binding, disable/enable, quit, upgrade, and uninstall on supported targets.
3. Verify that pending questions remain answerable in Codex after Pet exits.
4. Package tested architectures, release metadata, and SHA-256 checksums. Keep signing credentials in release secrets, never in Git.
5. Upload a GitHub prerelease for the exact tag and commit. Keep at least the previous working version available for rollback.

Publishing or changing visibility is an explicit action, not an automatic side effect of pushing to a branch. CI validation should be separate from a manually triggered release workflow.
