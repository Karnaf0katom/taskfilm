# Security

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/Karnaf0katom/taskfilm/security/advisories/new).
Use public issues for ordinary bugs. The latest alpha is the supported version.

Taskfilm is a local automation tool. Capture scripts can navigate pages,
interact with accounts, execute configured browser setup JavaScript and read
or write explicitly configured files. Use trusted scripts and target pages.
Browser automation does not isolate untrusted application code.

Fresh browser contexts are the default. Optional authentication state stays
outside take bundles. Redacted keystroke logs do not hide the visible screen;
review footage and filenames before sharing.

Keep credentials, profiles, cookies, private recordings and signed URLs out
of issues, examples and release bundles. Supply a small synthetic reproduction
when reporting a problem. Taskfilm has not had an independent security audit.
