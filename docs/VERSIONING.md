# Version management

`VERSION` and `CHANGELOG.md` describe the source version. A Git tag identifies an immutable source snapshot; a GitHub Release is a separate publication and does not imply a prebuilt app exists.

## Versions

| Version | Meaning |
| --- | --- |
| `0.1.0-prototype.1` | Historical browser prototype baseline; its tag is unchanged |
| `0.1.0-alpha.1` | Public source preview with native Codex integration and a source installer |
| `0.1.0-alpha.N` | Further preview milestones; increase the suffix for a new published snapshot |
| `0.1.0` | A future deliberately validated stable release |

The alpha is installed from source. It is not a signed, notarized app download. Visibility and maturity are independent: a public repository can remain experimental.

The native bundle uses a numeric `CFBundleShortVersionString` (`0.1.0`) and increasing `CFBundleVersion`; `PMPetSourceVersion` records the full preview version. Update these with `VERSION` for a release. Do not reuse a build number for a replacement published binary.

## Development workflow

- Use `codex/<change>` branches and focused commits.
- Review the user-visible behavior and run relevant checks before merging into `main`.
- Update the changelog for changes people installing the project should know about.
- Keep native generated bundles, runtime state, credentials, and signing material out of Git.
- Do not move an existing published tag or replace its assets. Publish a new version for a fix.

## Publishing a source preview

1. Review tracked files and reachable Git history for private runtime data and secrets; check the public-facing PR and release text too.
2. Verify the documented source installation in an isolated prefix, optional skill setup, update, and uninstall ownership behavior.
3. Run Python and JavaScript checks and build the native app from a clean source snapshot. Record what was tested on a real Mac and what remains unverified.
4. Merge the reviewed source and documentation into `main`.
5. Create the annotated `v<VERSION>` tag for that exact source. Publish release notes as a prerelease, clearly labeled **source preview**.
6. If changing visibility, do so only after the project owner explicitly requests it and the repository contents are ready.

## Future prebuilt app distribution

A downloadable app requires a separate distribution check: supported architectures, version metadata, installation/update/rollback behavior, signing and notarization, and SHA-256 checksums for immutable release assets. Credentials belong in release secrets, never source files. Do not advertise a Homebrew cask or one-command binary download before it exists and has been verified.
