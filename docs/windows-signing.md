# Windows signing

Status on 18 Nov 2026: Foundation application submitted; admission and a publicly trusted signing trial are pending. Do not enable release publication until that trial passes. A CI test certificate is not a public publisher identity.

## Provider choice

Recommend applying to **SignPath Foundation first**, subject to approval of the complete payload. No paid account has been opened.

| Option | Individual in Spain, cost and automation |
| --- | --- |
| [SignPath Foundation](https://signpath.org/) | Free service and certificate for accepted OSS projects. The certificate identifies **SignPath Foundation**, not the maintainer personally. GitHub-hosted builds and manual signing approval are required. Pianpian is public, MIT-licensed, maintained and already released; acceptance is **not confirmed**. Its modified FunASR helper needs explicit review under the [own-binaries/fork rules](https://signpath.org/terms). |
| [Microsoft Artifact Signing, formerly Trusted Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart) | Public Trust individual enrollment is limited to US/Canada, so **not eligible as an individual in Spain**. EU organizations are supported; do not assume a Spanish autónomo qualifies without Microsoft's confirmation. [Basic costs US$9.99/month](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-change-sku), including 5,000 signatures; excess US$0.005/signature. Requires a paid Azure subscription and identity validation. [GitHub Actions supports OIDC](https://github.com/Azure/artifact-signing-action); certificates renew daily with 72-hour validity, but identity revalidation remains manual. |
| Traditional CA certificate | A viable paid fallback is [SSL.com IV](https://www.ssl.com/products/software-integrity/code-signing/iv/): individual identity/address validation, with [Spain in its country list](https://www.ssl.com/country-codes/). The [published service selector](https://www.ssl.com/products/software-integrity/signing-service/) lists IV from US$129/year **plus** eSigner cloud subscription (annual Tier 1 equivalent US$15/month; confirm billing term, taxes and current checkout price before purchase). Its cloud service supports GitHub Actions. A USB token requires a machine with that token; it cannot simply be attached to a GitHub-hosted runner. [Sectigo](https://www.sectigo.com/ssl-certificates-tls/code-signing) advertises from US$536.25/year with a five-year purchase, plus applicable hardware/delivery charges. CA issuance, token/cloud terms and renewal are separate costs and steps; no purchase authorized. |

Authenticode authenticates signed bytes. The certificate identifies the publisher. [SmartScreen evaluates reputation separately](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation): even a correctly signed application, including EV, can still trigger warnings. Signing does not promise their removal.

## One-time setup

1. Apply at <https://signpath.org/apply> for `conradomateu/pianpian`; download page: <https://github.com/conradomateu/pianpian/releases>. Describe Python/pywebview/PyInstaller, Inno Setup, and the native helper sources in `tools/native/`. Specifically request review of the modified FunASR/ggml speech executable. Do not omit those binaries to work around Foundation policy.
2. Enable MFA on GitHub and SignPath. After acceptance, install the [SignPath GitHub App](https://github.com/apps/signpath) for this repository only. Link GitHub.com as the project's trusted build system.
3. Create project slug `pianpian`, policy slug `release-signing`, with the Foundation-issued public certificate, origin verification and the required manual approver. Permit only this repository and `.github/workflows/windows.yml`; permit the reviewed trial branch initially and release tags thereafter. Never allow unreviewed fork builds to request production signatures.
4. Import `tools/windows/windows-executables.xml` and `windows-installer.xml` as artifact configurations with those exact slugs. Their `version` parameter restricts ProductVersion; ProductName is `Pianpian`. Confirm both configurations with SignPath, including native helpers and the Inno uninstaller. There are two signing requests per build.
5. In [repository environments](https://github.com/conradomateu/pianpian/settings/environments), create `windows-signing`. Add secret **`SIGNPATH_API_TOKEN`**, from a SignPath CI user restricted to submitting requests for this project/policy. Add environment variables **`SIGNPATH_ORGANIZATION_ID`** and **`WINDOWS_SIGNING_SUBJECT`** (the exact certificate Subject string as reported by Windows, obtained from the approved public certificate). Never paste the token into chat, files, command arguments or logs. The official [SignPath action](https://docs.signpath.io/trusted-build-systems/github) requires an API token; it does not document OIDC authentication. No signing private key leaves the provider HSM.
6. After acceptance, add the required attribution “Free code signing provided by SignPath.io, certificate by SignPath Foundation” to the code signing policy, and link the policy from the public website/download page and release notes. Do not claim sponsorship before acceptance.
7. Run a trial from the reviewed PR branch (the `windows` workflow already exists on main):

   ```sh
   gh workflow run windows.yml --repo conradomateu/pianpian --ref ci/windows-signing
   gh run list --repo conradomateu/pianpian --workflow windows.yml --branch ci/windows-signing
   ```

   Approve both requests in SignPath: first five executable files, then the installer. Each waits up to one hour. A manual dispatch **never publishes a release**. Download the `Pianpian-Windows` artifact from the successful run. Its installer and ZIP have passed Windows signature/timestamp checks and a silent install, payload comparison and uninstall. Check launch/playback on a real Windows machine too; CI does not establish SmartScreen reputation or interactive app behavior.
8. Only after that public-certificate trial is verified, add repository variable **`WINDOWS_SIGNING_TEST_RUN`** with the successful run's full GitHub URL. It is a maintainer-controlled rollout gate, not an automatic proof of approval. Do not set it to a CI fixture run. Review/merge the PR after the trial; do not create a release to test signing.

## What CI enforces

`windows.yml` requires credentials even for manual trials. It builds the app, generates Inno's unsigned uninstaller in its [external-signing mode](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm), and submits exactly:

- `Pianpian.exe`
- `pianpian-align.exe`
- `pianpian-sensevoice.exe` and `pianpian-sensevoice-avx2.exe`
- `uninstaller.exe` (the staged Inno executable, restored under Inno's original cache name after signing)

It verifies all five before packaging, then signs/verifies `Pianpian-Windows-Setup.exe`. [SignPath's file-based signing manages timestamps](https://docs.signpath.io/crypto-providers/); `signtool verify /pa /all /tw` and `Get-AuthenticodeSignature` reject missing timestamps, invalid trust, missing embedded signatures and an unexpected Subject. Both configurations request SHA-256. Any error stops the job.

All other packaged bytes, including uv, Python, WebView2/.NET and MSVC components, must remain identical. No recursive signing or replacement of upstream signatures. ZIP contents and installed files must match the verified app. Native build manifests describe the **unsigned build**, while `windows-signing-verification.json` contains hashes of the final signed distribution. Logs include public certificate identities/hashes, never tokens or private keys. Only explicit output paths become artifacts.

Release-please creates a **draft** release and a tag. Publication waits for both macOS and Windows jobs; failed signing leaves the release unpublished. Recovery is rerunning the failed workflow jobs after fixing configuration, not manually uploading unsigned files or publishing the draft. PR CI uses a disposable non-exportable certificate trusted only on its runner; its artifact is explicitly labelled **TEST-CERT-NOT-FOR-DISTRIBUTION**.

## Renewal

The workflow references a SignPath policy, not a local certificate/PFX or a pinned thumbprint. Certificate replacement under that policy therefore requires no key deployment or workflow edit if the Subject stays the same. Foundation controls certificate issuance/replacement: confirm its renewal arrangements during enrollment; the public documentation does not establish a client renewal API, so no speculative renewal script is installed. Monitor its renewal notices and rotate the CI API token in GitHub Secrets when required. An expired/unavailable certificate or missing timestamp stops distribution. Update the expected Subject only after independently verifying an intentional publisher change.
