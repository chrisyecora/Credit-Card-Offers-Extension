## Usage

### Multi-bank data

Migration `0002_create_banks.sql` drops the old `offers` table and creates
`banks` plus bank-scoped offers. Applying it deletes existing offers. After
configuring Cloudflare credentials, run from `offers-api/`:

```
npm exec wrangler -- d1 migrations apply offers-db --remote
python3 scripts/load_offers.py --apply
```

The loader accepts the existing Capital One `offers.json`. New bank feeds should
provide `bank_slug` (lowercase letters, digits, and underscores) and `bank` (the
display name) on every offer. Raw offer IDs only need to be unique within their
bank. `/v1/offers?domain=example.com` returns offers from every loaded bank,
including both `bank` and `bank_slug` in each result.

You can run the Worker defined by your new project by executing `wrangler dev` in this
directory. This will start up an HTTP server and will allow you to iterate on your
Worker without having to restart `wrangler`.

### Types and autocomplete

This project also includes a pyproject.toml with some requirements which
set up autocomplete and type hints for this Python Workers project.

To get these installed you'll need `uv`, which you can install by following
https://docs.astral.sh/uv/getting-started/installation/.

Once `uv` is installed, you can run the following:

```
uv venv
uv sync
```

Then point your editor's Python plugin at the `.venv` directory. You should then have working
autocomplete and type information in your editor.
