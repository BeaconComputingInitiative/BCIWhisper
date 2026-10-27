<!-- BEACON COMPUTING INITIATIVE | Developer Seal: CJB-DEV-2026 | Chance Joaquin Boone -->
<!-- SHA-256: see docs/HYGIENE_SHA256SUMS -->

# Repository review: BCIWhisper

Reviewed: October 26, 2026. Default branch: `master`. Audited commit: `882a3eace8e4f9b7a1a8bf8755743a452126662e`.

## Verified findings and follow-up

- `master` identifies the pre-Studio 58.4 source boundary, while the longer README still describes the 57.10 release baseline. These are distinct source and release states.
- Published release `v6.0-script60.0` is still named Podcast Lab / Studio under Whisper. That historical asset can confuse visitors even though Studio now has its own repository. Preserve it until an accepted Studio replacement exists; then clearly label it historical and point visitors to BCIStudio.
- `versions/recovery-snapshots/` contains historical Python package files in the active checkout. Preserve history, check installer/manifest references, and migrate recoveries to a tag or release asset before removing these paths.
- `android/` remains in this desktop repository while BCIAndroid owns a newer Android application. Mark the desktop copy historical or remove it only after checking build workflows and submodule references.
- `BCIWhisper.py`, `bci/`, `bci_audio/`, `bci_core/`, and `bciwhisper/` coexist as legacy and modular runtime layers. Keep compatibility until import and packaging checks prove safe removal.
- Existing draft PR #4 overlaps the Studio separation. Compare it against the present pre-Studio default branch before merging; it was not merged by this audit.

## Repository rules

- Maintain one documented current source tree and one supported starting point per product/platform. Give genuinely distinct tools purpose-based names.
- Use Git commits, branches and tags for revisions. Avoid final, latest, new, old, backup and copy suffixes on source files.
- Put downloadable builds and checksums in GitHub Releases. Keep recordings, telemetry, local environments and generated dependencies outside tracked source.
- Keep version-qualified protocol/API names and regression-test names when they describe an actual compatibility contract.
- Write commits as a concrete action and affected component, followed by the reason and relevant validation when needed. A late-night timestamp alone is not a quality defect.
- Release if and only if the documented acceptance gates pass on the exact release commit. Clearly label previews, recovered source, device validation gaps and historical releases.
- Keep the BCI header and developer seal on new authored files. Record their exact bytes in a SHA-256 manifest; do not attempt a self-referential file hash.

## Automated prevention

`Repository hygiene` runs on pushes and pull requests with read-only repository permissions. It inspects tracked files without executing project/application code. It rejects new confusing copy-style filenames, generated/runtime artifacts, recovery snapshot directories and byte-identical nonempty source copies. Existing paths are grandfathered against the audited commit, so this is prevention rather than a claim that historical issues are resolved. Empty package initializers are excluded from duplicate detection. Dataset duplicates are reported separately and left untouched.

Run locally: `python3 tools/repository_hygiene.py --baseline 882a3eace8e4f9b7a1a8bf8755743a452126662e` and `sha256sum -c docs/HYGIENE_SHA256SUMS`.

This workflow checks pushes and pull requests after integration, and it does not become a mandatory branch-protection rule automatically. It cannot prove semantic equivalence, runtime correctness, README accuracy or release readiness. Intentional shared code should be extracted into a common module; deliberate compatibility exceptions require a reviewed policy adjustment.

## Extended history audit

See [PORTFOLIO_AUDIT.md](PORTFOLIO_AUDIT.md) for the complete branch-history inventory, consolidation decisions and current review limits. The original findings above describe the pre-cleanup snapshot; the portfolio audit and README record the resulting state.
