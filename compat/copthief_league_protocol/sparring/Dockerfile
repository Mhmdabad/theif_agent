# The sparring peer, self-certifying at startup.
#
# Build from the REPOSITORY ROOT, not from this directory:
#     docker build -f sparring/Dockerfile -t copthief-sparring .
#
# The kit's own checker and vectors are copied in on purpose. The peer imports its byte-level
# constructions from verify_vectors.py rather than vendoring them, and its preflight re-runs the
# published vectors inside the container — so the image proves it reproduces them on the Python it
# actually runs, instead of trusting that it did on someone's laptop.

FROM python:3.12-slim

WORKDIR /kit

# The kit's constructions and fixtures, then the peer. Copying these first keeps the layer stable
# across peer edits.
COPY verify_vectors.py ./
COPY vectors ./vectors
COPY sparring/requirements.txt ./sparring/requirements.txt

RUN pip install --no-cache-dir -r sparring/requirements.txt

COPY sparring ./sparring

# Nothing here needs root, and a practice peer other people run should not have it.
RUN useradd --create-home --shell /usr/sbin/nologin spar \
    && mkdir -p /kit/runs && chown -R spar:spar /kit
USER spar

EXPOSE 8931

# `python -m` from /kit is what lets `import verify_vectors` resolve with no packaging and no
# path juggling — the same invariant as running from a clone.
ENTRYPOINT ["python", "-m", "sparring.cli"]
CMD ["selfplay"]
