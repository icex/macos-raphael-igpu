# Candidate 186 frozen run

The audited headless Lilu path initialized successfully: the exact build marker,
`-liluheadless rgpudump=5000`, patcher readiness, and AMD `loadKinfo` callbacks
were captured. Route installation completed, but KIQ ownership was refused due
to a missing valid owned lease; PM4 power-up and `powerUpHWEngines` therefore
did not pass. WindowServer later panicked in `endVMPTUpdate` with CR2 zero.

The run produced no Metal probe result and no recovery receipt. Recovery was
refused because the native recovery lease records lacked XH2 ownership. VM
shutdown completed; GPU recovery was refused and remains unverified. This is GPU
cycle 8 overall and cycle 4
since the post-Astra candidate-182 boundary. No retry is authorized by this
evidence.
