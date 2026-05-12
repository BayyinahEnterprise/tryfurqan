# tryfurqan.com

Landing page and live playground for [furqan-lint](https://github.com/BayyinahEnterprise/furqan-lint),
the structural-honesty static checker for Python, Rust, and Go --
plus a sister demo for the [Furqan programming language](https://github.com/BayyinahEnterprise/furqan-programming-language)
that derived the architecture.

As of v1.0.0 (al-Basirah, Phase G12.0) furqan-lint signs its own
release with Sigstore and exposes Relying-Party verification
through `furqan-lint manifest verify-self`. v1.0.0 closes the
canonical mushaf substrate-chain that started at v0.11.1.

## What this site is

A FastAPI app that serves three surfaces:

- `GET /` -- the editorial landing page: thesis, install, checks,
  verdicts, self-attestation, sister substrate (the Furqan
  language), and the research index of Zenodo-deposited papers.
- `GET /playground` -- the live furqan-lint playground. Paste a
  Python / Rust / Go function, see the same D11 status-coverage
  verdict the CLI fires. Supports the `furqan-lint diff` mode
  across two versions of a module's public surface, with
  shareable snapshot URLs (30-day TTL).
- `GET /demo` -- the legacy Furqan-language demo. Paste a
  `.furqan` module or pick an exhibit; the language's own
  type-checker returns one of four verdicts.

Both `POST /demo/check` and the playground's check / diff
endpoints write user source to a per-request tmp file under
`/tmp`, invoke the appropriate checker in a subprocess with a
5-second wall-clock cap and a 100 KiB input cap, capture the
verdict from exit code and stdout, then delete the tmp file. No
source is logged.

## Verdicts

| Verdict       | Meaning                                                                  |
|---------------|--------------------------------------------------------------------------|
| `PASS`        | All applicable checks ran. Zero marads, zero advisories.                 |
| `MARAD`       | At least one structural violation. Diagnosis and minimal fix included.   |
| `ADVISORY`    | Informational findings only. The module passes, with notes.              |
| `PARSE ERROR` | The source could not be parsed. Reported with line and column.           |

These are furqan-lint's and Furqan's shared vocabulary. The site
does not borrow Bayyinah's sahih / munafiq / mughlaq taxonomy
because the code-structure domain (furqan-lint, Furqan) and the
file-integrity domain (Bayyinah) are different products with
different audiences.

## Local development

```bash
git clone https://github.com/BayyinahEnterprise/tryfurqan
cd tryfurqan
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

Then open <http://localhost:8000> for the landing page,
<http://localhost:8000/playground> for the furqan-lint live
checker, and <http://localhost:8000/demo> for the Furqan-language
demo.

## Deployment

The app is deployed to Railway from `main`. Cloudflare points
`tryfurqan.com` at the Railway service.

| File             | Purpose                                                                              |
|------------------|--------------------------------------------------------------------------------------|
| `api.py`         | FastAPI application: landing, playground, demo, sandbox.                             |
| `static/`        | `index.html`, `playground.html`, `playground.js`, `demo.html`, `demo.js`, OG card.   |
| `fixtures/`      | Whitelisted `.furqan` and lint exhibits.                                             |
| `Procfile`       | `uvicorn` start command for Railway.                                                 |
| `railway.json`   | Healthcheck, restart policy, builder config.                                         |
| `nixpacks.toml`  | Go toolchain installation for the `furqan-lint[go]` adapter at build time.           |
| `requirements.txt` | Pinned: FastAPI, uvicorn, pydantic, furqan v0.11.1, furqan-lint[go,rust] v1.0.0.  |

## Sister project

[Bayyinah](https://bayyinah.dev) is the file-integrity scanner
that applies the same structural-honesty discipline at the input
layer of an AI pipeline. Same lab (BayyinahEnterprise), different
surface.
