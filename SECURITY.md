# Security policy

Report a plausible vulnerability privately through GitHub's private vulnerability
reporting when available. Do not post unpatched exploit material in public issues.

The Studio is a local experiment tool bound to 127.0.0.1. Fixed subprocesses,
strict input schemas, host/origin checks and resource limits reduce accidental
misuse; they are not a general-purpose sandbox or authorization to expose it on
the public internet. The portable runner executes included Python source, which
you should inspect before running an archive obtained from another person.

Numerical/model limitations belong in ordinary reproducible issues. A good
radio fit is not a claim of physical accuracy or a security guarantee.
