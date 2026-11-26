# Publishing Agentnik to PyPI

The first candidate is `0.12.0rc1`. The desktop ZIP release series is separate. Keep the candidate version in `pyproject.toml` and `agentnik/__init__.py` in sync before building.

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

Sign in to PyPI as `nikspence` to manage the project. For Twine token uploads, use `__token__` as the username and the token as the password. Use Twine's credential prompt or a credential store. Do not commit credentials. An ongoing GitHub release workflow can use [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) instead of an API token. The GitHub repository is `nikspence/agentnik`. Publishing is not part of ordinary CI.
