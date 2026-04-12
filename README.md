# Candidate Webserver (App Repo)

This repository contains the source code for a lightweight, dockerized web server built to satisfy the DevOps O&Si candidate assessment.

## Features

- **Client-Side Rendering**: In order to guarantee accuracy for globally distributed users, the timestamp is rendered dynamically at the edge using client-side JavaScript instead of relying on the server's backend timezone, displaying the user's local browser time natively.
- **OpenShift Compatibility**: The Dockerfile builds an image explicitly designed to support OpenShift's arbitrary UID approach. It uses port `8080`, and correctly applies `chgrp 0` to required configuration and cache paths so any assigned non-root user can run it perfectly.
- **CI Pipeline**: Includes a GitHub Action workflow to lint the HTML, build the container, perform static vulnerability analysis (Trivy), push the image, and output what *would* be the commit step to the downstream `repo-platform`.

## Running Locally

Build the image:
```sh
docker build -t devops-test-webserver:latest .
```

Run the image locally:
```sh
docker run -p 8080:8080 devops-test-webserver:latest
```

Visit `http://localhost:8080`. You will see `Hello DevOps O&Si Vedant Aggrawal` and the dynamic local time of the request.
