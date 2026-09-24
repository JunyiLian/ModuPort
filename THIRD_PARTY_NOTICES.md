# Licensing and provenance review

The following bundled source groups are required by the validated solver but
do not yet have confirmed ownership or licensing metadata:

- `src/moduport/_vendor/rv30/`
- `src/moduport/_vendor/mscsolver/`

The A1 source manifest records these groups as internal external dependencies.
They must not be silently placed under a new licence. Legal/owner confirmation
is required before public distribution.

The authoritative solver under `src/moduport/_frozen/` and both vendor groups
remain byte-for-byte frozen against the A1 SHA-256 manifest. Two frozen/internal
files contain historical local-path strings:

- `src/moduport/_frozen/runtime.py`
- `src/moduport/_vendor/rv30/a20_rv30_moduport_adapter.py`

The portable bootstrap prevents those paths from being required at runtime.
They cannot be removed without changing frozen bytes, so they remain a release
review item rather than being edited for presentation purposes.

