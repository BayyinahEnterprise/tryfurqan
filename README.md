# tryfurqan.com

Landing page and live demo for [Furqan](https://github.com/BayyinahEnterprise/furqan-programming-language),
a programming-language type-checker that enforces structural honesty
at compile time.

## What this site is

A FastAPI app that serves two surfaces:

- `GET /` is the editorial landing page with the thesis, install
  command, and verdict reference.
- `GET /demo` lets you paste a `.furqan` module or pick an exhibit;
  the live checker returns one of four verdicts in milliseconds.

The demo's `POST /demo/check` endpoint runs the source through
`python -m furqan check` in a subprocess sandbox with a 5-second
wall-clock cap and a 64 KiB input cap. The verdict is derived from
the CLI's exit code and stdout, which is the contract the package
documents.

## Verdicts

| Verdict       | Meaning                                                                  |
|---------------|--------------------------------------------------------------------------|
| `PASS`        | All nine checkers ran. Zero marads, zero advisories.                     |
| `MARAD`       | At least one structural violation. Diagnosis and minimal fix included.   |
| `ADVISORY`    | Informational findings only. The module passes, with notes.              |
| `PARSE ERROR` | The source could not be parsed. Reported with line and column.           |

These are Furqan's own vocabulary. The site does not borrow Bayyinah's
sahih / munafiq / mughlaq taxonomy because Furqan's domain (programming
language structure) and Bayyinah's domain (file integrity) are different
products with different audiences.

## Local development

```bash
git clone https://github.com/BayyinahEnterprise/tryfurqan
cd tryfurqan
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

Then open <http://localhost:8000> for the landing page and
<http://localhost:8000/demo> for the live checker.

## Deployment

The app is deployed to Railway from `main`. Cloudflare points
`tryfurqan.com` at the Railway service.

| File             | Purpose                                            |
|------------------|----------------------------------------------------|
| `api.py`         | FastAPI application (landing, demo, sandbox).      |
| `static/`        | `index.html`, `demo.html`, `demo.js`, OG card.     |
| `fixtures/`      | Five whitelisted `.furqan` exhibits.               |
| `Procfile`       | `uvicorn` start command for Railway.               |
| `railway.json`   | Healthcheck, restart policy, builder config.       |
| `requirements.txt` | Pinned: FastAPI, uvicorn, pydantic, furqan v0.10.1. |

## Sister project

[Bayyinah](https://bayyinah.dev) is the file-integrity scanner
that applies the same structural-honesty discipline at the input
layer of an AI pipeline. Same lab, different surface.
