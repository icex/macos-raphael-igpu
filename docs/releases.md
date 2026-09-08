# Experimental releases

GitHub Actions runs host-independent tests on `main`, `dev`, pull requests and `v*` tags.
It compiles an x86_64 `MH_KEXT_BUNDLE` from the checked-out source using pinned
MacKernelSDK and Lilu build inputs, then uploads a ZIP and SHA-256 checksum file.
A `v*` tag publishes the verified build assets as a GitHub **prerelease** only after
both test and build jobs pass. Untagged builds produce workflow artifacts.

The ZIP includes `RaphaelGPU.kext`, documentation, AMD firmware licence and a build
manifest containing the source commit and executable/input hashes. The build never
falls back to `kext/bin/RaphaelGPU`. It does not start a VM, access PCI hardware,
install a driver, sign a host kernel or change boot configuration. Hosted CI cannot
validate this machine's KDK offsets, physical GPU execution or host stability.

The runner label is explicitly Intel, as listed in the
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Local build

With the Linux cross-toolchain prepared by `tools/bootstrap-toolchain.sh`:

```sh
python3 -B tools/build-release.py --toolchain /path/to/toolchain --output /tmp/rgpu-dist
```

On macOS, prepare `MacKernelSDK-master` and `liludbg` using the workflow's pinned
inputs (directory-content hashes are checked on both platforms), and set `KEXT_LD="$(xcrun --find ld)"`. The generated firmware header is
validated against `build-support/inputs.json`; no firmware or KDK downloads are
required during compilation.

## Validation and installation limits

The release is a research snapshot: Metal execution fails and no games are verified.
Use the matching 24G830 KDK and VM harness preflight before any experimental deployment.
OpenCore must inject both Lilu and RaphaelGPU into the boot kernel collection;
`-lilubetaall` is required for the tested Sequoia setup. The kext alone does not
configure the required VBIOS graft, device spoofing or patch mask. Do not use historical
AuxKC deployment instructions as the primary delivery path.

Host passthrough restrictions remain binding: amdgpu must initialize the iGPU this boot,
no driver cycling, no virgin VFIO override, no forced HQD clear or platform reset.
Release build success is not a Metal test result.
