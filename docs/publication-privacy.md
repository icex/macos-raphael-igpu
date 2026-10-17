# Publication privacy

Published research paths and local network/device identifiers are anonymized
examples. Private OpenCore identity dumps and browser-history captures are
excluded from the complete published history. Original evidence and runtime
recovery receipts are retained only in private local storage; historical
content hashes describe those original artifacts, not redacted text.

The desktop installation and VM data are independent of the sanitized source
publication. No guest restart, shared-drive change or runtime identity rewrite
is required for this cleanup. No startup test or session expiry is added.

Before pushing, run `python3 -B tools/privacy-check.py` and Gitleaks with the
repository configuration. The Gitleaks allowlist contains only reviewed literal
artifact digests and observation markers, never generic credential patterns.
Never commit keychains, password databases, account tokens, OpenCore identities,
or screenshots of personal browser activity. Keep raw private evidence outside
Git. Example paths must use a generic account; executable defaults use the home
of the current user.
