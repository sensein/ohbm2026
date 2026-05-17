# Contract: GitHub Action Workflows

Three workflows govern the site lifecycle. Each has a single trigger and a single responsibility (per research.md R8).

## 1. `.github/workflows/deploy-ui.yml`

**Trigger**: `push` to `main` (paths: `src/ohbm2026/**`, `scripts/build_ui_data.py`, `site/**`, `specs/008-ui-rewrite/contracts/references.yaml`).

**Job: `deploy-production`**

```yaml
runs-on: ubuntu-latest
concurrency: { group: deploy-ui-production, cancel-in-progress: false }
permissions:
  contents: write
  pages: write
steps:
  - name: Checkout
    uses: actions/checkout@v4
    with: { fetch-depth: 0 }   # full history for code_revision

  - name: Set up Python 3.14
    uses: actions/setup-python@v5
    with: { python-version: "3.14" }

  - name: Install uv + repo deps
    run: |
      pip install uv
      uv venv --python 3.14 .venv
      uv pip install --python .venv/bin/python -e ".[ui,enrich]"

  - name: Set up Node 20 + pnpm
    uses: actions/setup-node@v4
    with: { node-version: "20" }
  - run: corepack enable && corepack prepare pnpm@9 --activate

  - name: Install site deps
    working-directory: site
    run: pnpm install --frozen-lockfile

  - name: Restore corpus + Stage 4 artifacts
    run: |
      # The corpus + rollup + embeddings live outside the repo (gitignored).
      # Production deploy fetches them from a release artifact or a tracked DVC store.
      # Implementation detail handled by `scripts/fetch_ui_inputs.sh`.
      ./scripts/fetch_ui_inputs.sh

  - name: Build data package (state-keys discovered at runtime per CA-007)
    run: |
      PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
        --corpus data/primary/abstracts.json \
        --withdrawn data/primary/abstracts_withdrawn.json \
        --authors data/primary/authors.json \
        --enriched data/primary/abstracts_enriched.sqlite \
        --references data/primary/reference_metadata.json \
        --analysis-root data/outputs/analysis \
        --discover-rollup \
        --minilm-bundle "$(PYTHONPATH=src .venv/bin/python -m ohbm2026.ui_data.state_key minilm data/outputs/embeddings/minilm title)" \
        --references-yaml specs/008-ui-rewrite/contracts/references.yaml \
        --output site/static/data/

  - name: Run Python unit tests
    run: PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p "test_ui_data*"

  - name: Run site unit tests (Vitest)
    working-directory: site
    run: pnpm test:unit -- --run

  - name: Build site (SvelteKit static-adapter)
    working-directory: site
    run: pnpm build

  - name: Run Playwright smoke
    working-directory: site
    run: pnpm test:e2e --reporter=line

  - name: Publish to gh-pages root
    uses: peaceiris/actions-gh-pages@v3
    with:
      github_token: ${{ secrets.GITHUB_TOKEN }}
      publish_dir: site/build
      publish_branch: gh-pages
      destination_dir: .
      keep_files: true   # Preserve /pr-<N>/ subdirectories from preview workflow
      enable_jekyll: false
      commit_message: |
        deploy(ui): ${{ github.sha }}
```

## 2. `.github/workflows/pr-preview.yml`

**Trigger**: `pull_request` (events: `opened`, `synchronize`, `reopened`).

**Surface**: the preview URL surfaces in the **PR's Deployments box** (top-of-PR, populated by the workflow's `environment:` declaration). No bot comment is posted in the conversation. GitHub auto-creates the `pr-preview-<N>` environment on first use; subsequent pushes update the same environment URL in place.

**Job: `deploy-preview`**

```yaml
runs-on: ubuntu-latest
concurrency: { group: deploy-ui-preview-pr-${{ github.event.pull_request.number }}, cancel-in-progress: true }
permissions:
  contents: write    # gh-pages branch push
  deployments: write # create/update the deployment entry
if: github.event.pull_request.head.repo.full_name == github.repository  # skip forks
environment:
  name: pr-preview-${{ github.event.pull_request.number }}
  # NOTE: this URL surfaces in the PR's Deployments box at the top of the PR.
  # GitHub auto-creates the environment on first deploy. The URL stays attached
  # to the environment across pushes so the same deployment entry is updated
  # in place — no comment churn.
  url: https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/pr-${{ github.event.pull_request.number }}/
steps:
  # ...Steps 1-7 identical to deploy-production EXCEPT:
  - name: Publish to gh-pages subdirectory
    uses: peaceiris/actions-gh-pages@v3
    with:
      github_token: ${{ secrets.GITHUB_TOKEN }}
      publish_dir: site/build
      publish_branch: gh-pages
      destination_dir: pr-${{ github.event.pull_request.number }}
      keep_files: true
      enable_jekyll: false
      commit_message: |
        preview(ui): pr-${{ github.event.pull_request.number }} ${{ github.sha }}
```

**Note**: no `peter-evans/find-comment` or `create-or-update-comment` step. The GitHub Deployments API (auto-populated from `environment:`) handles the PR-surface affordance natively. Reviewers see "View deployment" → `pr-preview-<N>` at the top of the PR, above the file diff and below the description.

## 3. `.github/workflows/pr-preview-cleanup.yml`

**Trigger**: `pull_request` (event: `closed`).

**Job: `cleanup-preview`** — removes the `/pr-<N>/` directory from `gh-pages` AND marks the `pr-preview-<N>` deployment as **inactive** via the GitHub Deployments API. After cleanup, the PR's Deployments box shows the deployment in the inactive state with no live link.

```yaml
runs-on: ubuntu-latest
permissions:
  contents: write       # gh-pages branch push
  deployments: write    # mark deployment inactive
if: github.event.pull_request.head.repo.full_name == github.repository
steps:
  - uses: actions/checkout@v4
    with: { ref: gh-pages, fetch-depth: 1 }

  - name: Remove preview directory
    run: |
      rm -rf pr-${{ github.event.pull_request.number }}
      git config user.name "github-actions[bot]"
      git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      git add -A
      if git diff --staged --quiet; then
        echo "No preview directory to remove."
      else
        git commit -m "cleanup(ui): remove pr-${{ github.event.pull_request.number }} preview"
        git push
      fi

  - name: Mark pr-preview-<N> deployment inactive
    uses: actions/github-script@v7
    env:
      PR_NUMBER: ${{ github.event.pull_request.number }}
    with:
      script: |
        const envName = `pr-preview-${process.env.PR_NUMBER}`;
        // List active deployments for this environment and set each to inactive.
        const deployments = await github.rest.repos.listDeployments({
          owner: context.repo.owner,
          repo: context.repo.repo,
          environment: envName,
          per_page: 100,
        });
        for (const dep of deployments.data) {
          await github.rest.repos.createDeploymentStatus({
            owner: context.repo.owner,
            repo: context.repo.repo,
            deployment_id: dep.id,
            state: "inactive",
            description: "PR closed; preview cleaned up.",
          });
        }
```

**Note**: no PR-conversation comment is posted on cleanup either — the Deployments box state ("Inactive") is the surface that signals the preview is gone.

## Required Pages settings (one-time, manual)

- GitHub Pages: **source = `gh-pages` branch / root** (the default after the first publish).
- Custom domain (optional): set in repo settings → Pages.
- Enforce HTTPS: ON.

## Secrets

- Only `GITHUB_TOKEN` (auto-provisioned per workflow). **No** OpenAI / Anthropic / Voyage / other API keys touch the deploy path — the data package is built from pre-computed Stage 1–4 artifacts. (CA-004.)

## Time + cost budget

- Per-workflow run: ≤ 10 min p90 (SC-008). Dominated by the data-package build (~3 min for 3,244 abstracts + the link checker).
- Free-tier `ubuntu-latest` minutes are sufficient at expected PR cadence.
