# Contributing

Start with a small reproducible measurement or scene and the observed outcome.
Explain whether it is simulation, recorded data or hardware observation. Preserve
separate truth and blind inputs. Changes to scientific claims need independent
controls or a falsifier, not a more confident label.

Run `python -m unittest discover -s tests -v`. Keep browser modules dependency
free unless a new library earns its installation and maintenance cost. Report
AI assistance and verification limits truthfully; don't submit fabricated
measurements or overwrite somebody else's source attribution.

With Node 20+, `node tests/studio-inputs.mjs studio/app.js` checks that actual
editor input handlers send edited coordinates and reject invalid drafts. It
uses a minimal DOM harness; browser interaction remains a separate check.

Discuss new hardware/model families in an issue before a large implementation.
The present packet schema intentionally rejects unmodeled fields.
