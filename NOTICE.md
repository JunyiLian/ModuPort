# Notice

ModuPort is independently developed research software by Jun-Yi Lian.

The bundled `mscsolver` and RV30 adapter components belong to the same ModuPort
development lineage and are distributed with ModuPort under the MIT License.
The validated solver core and these internal dependencies remain byte-for-byte
frozen in this release to preserve numerical reproducibility.

Two frozen files retain historical local-path strings. These strings are
inactive in the portable release bootstrap, provide no credential, private
resource, or external-access capability, and remain only because changing them
would alter the frozen source hashes.

Research datasets, SAP2000 files and automation, A30/A32 case data, benchmark
outputs, figures, manuscript results, and other research data are not included
in this repository.

Third-party Python packages used by ModuPort remain subject to their own
licenses and are not relicensed by this notice.
