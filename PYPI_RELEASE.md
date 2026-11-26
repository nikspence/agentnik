# Publishing Agentnik to PyPI

The first candidate is `0.12.0rc1`. The desktop ZIP release series is separate. Keep the candidate version in `pyproject.toml` and `agentnik/__init__.py` in sync before building.

## GitHub Trusted Publishing

While signed in to PyPI as `nikspence`, register a pending GitHub publisher with these values:

| Field | Value |
| --- | --- |
| PyPI project name | `agentnik` |
| GitHub owner | `nikspence` |
| Repository name | `agentnik` |
| Workflow name | `publish-to-pypi.yml` |
| Environment name | `pypi` |

Create a GitHub environment named `pypi`. Restrict it to release tags and configure required reviewers if your repository supports them. The workflow only runs when manually dispatched. Leave **Upload** unchecked for a build and artifact review. When the TUI is ready for testing, create the matching version tag on the verified commit, select that tag in the workflow dispatch, and explicitly enable **Upload**. The workflow checks that the tag and both version declarations match before publishing. It uses Trusted Publishing without a PyPI API token.

## Local build and manual fallback

To publish the original desktop-only `0.11.1`, dispatch the workflow from `master` with the historical release option selected. It checks out the exact commit behind `v0.11.1`, because that tag predates the publishing workflow. The upload option is still off by default. If you restrict the GitHub `pypi` environment to release tags, temporarily allow `master` for this historical dispatch or use the manual upload route.

From a clean checkout, use Python 3.11 or newer. Build into an empty output directory so checks and uploads apply to a single version:

```sh
python -m pip install build twine
python -m build --outdir dist/pypi
python -m twine check --strict dist/pypi/*
```

Install the built wheel with the `terminal` extra into a clean virtual environment. From a folder outside the checkout, run `agentnik code --help` and verify that Qt is absent. In a separate environment install the same wheel with the `desktop` extra and check the desktop launcher and packaged assets. Run the offline CI jobs and review both artifacts before uploading.

Once you are ready to publish, upload to [TestPyPI](https://test.pypi.org/) using a TestPyPI token and check the project page and install. To avoid resolving unrelated dependencies from TestPyPI, install dependencies from PyPI and install the candidate itself from TestPyPI with `--no-deps`.

```sh
python -m twine upload --repository testpypi dist/pypi/*
```

After review, upload the same checked files to [PyPI](https://pypi.org/) using a PyPI token:

```sh
python -m twine upload dist/pypi/*
```

For Twine token uploads, use `__token__` as the username and the token as the password. Use Twine's credential prompt or a credential store. Do not commit credentials. Publishing is not part of ordinary CI.
