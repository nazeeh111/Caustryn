# Changelog

## 0.2.1

Phaseglass is now **Caustryn**. The README, local Studio and recorded browser
replay use the new identity and source links. The original simulation models,
solver, training/held-position policy and recorded 0.2.0 calculations remain
unchanged. This release adds no new sensing or scientific capability.

`caustryn` is the preferred console command. The existing `phaseglass` command
calls exactly the same implementation and remains available. The Python
distribution, imports, JSON schemas and portable replay layout retain their
original names so existing scripts and experiments continue to work.

Existing release tags and assets are preserved. The original `/Phaseglass/`
browser replay is retained separately; the canonical project uses `/Caustryn/`.
