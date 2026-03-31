# Debugging

- The initial NOCD attempt failed because the available local `nocd` checkout
  only exposed `sampler.py` and did not include `nocd.model.NOCD`.
- Rather than trying to pull unverified external code into the environment, the
  overlap experiment switched to a `GaussianMixture`-based soft-membership
  approach that worked with the libraries already available in the repo venv.
