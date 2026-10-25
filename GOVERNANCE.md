# Governance

## Maintainer

Matt Macosko ([@nicedreamzapp](https://github.com/nicedreamzapp)) is the maintainer. He reviews and merges every pull request and cuts every release.

## How changes get in

- Anyone can open an issue or a pull request.
- Pull requests that change behavior should include tests. The tool call parser has its own tests that run without a model (`tests/test_parse_tool_calls.py`), and CI runs the test suite on every pull request.
- The maintainer reviews, asks for changes if needed, and merges. Nothing is merged with failing CI.

## Releases

Releases are tagged on `main` with notes describing what changed.

## Security

Security reports go through GitHub's private reporting, as described in [SECURITY.md](SECURITY.md).

## Conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
