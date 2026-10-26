# Dependencies and provenance

Caustryn application, forward model, inverse search, studio and experiment
fixtures are original MIT code. No third-party WiFi application source, trained
weights or empirical measurements are bundled.

NumPy and SciPy are separately installed dependencies. Both use BSD licenses;
their installed distributions contain their complete licenses and notices for
bundled numerical libraries. Caustryn does not relicense them.

The mechanisms are established mathematical techniques: bistatic path length,
complex least squares, profiling nuisance gains, finite initialization search,
bounded local optimization and singular-value analysis. This release does not
claim their invention or universal uniqueness of its reconstruction.

All included IQ is simulated under the explicitly stated point-scatterer model.
Generated evidence is not a recording from WiFi hardware. Dependencies, source
comparisons and engineering research do not constitute external validation.
