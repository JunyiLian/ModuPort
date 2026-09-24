# Contributing

Contributions to documentation, examples, tests, packaging, the public API,
layout enumeration, and the web interface are welcome.

Do not edit files in `src/moduport/_frozen/` or the frozen vendor dependency
groups. Any proposed mechanics change requires a separate validation campaign
and must not be mixed with ordinary packaging or interface work.

Before submitting a change:

1. Run `python -m unittest discover -s tests -v`.
2. Confirm the A1 frozen-source hashes remain 26/26 exact.
3. Check that no research data, local paths, credentials, or generated outputs
   have entered the repository.
4. Keep API and web-interface calls on the same `ModuPort` facade.
