import json
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).parents[2] / "deploy"
SERVER_IMAGE = "ghcr.io/sboogway/sbt2-server"


@pytest.mark.unit
def test_policy_requires_a_sigstore_signature_for_the_server_image() -> None:
    policy = json.loads((DEPLOY / "policy.json").read_text())

    [requirement] = policy["transports"]["docker"][SERVER_IMAGE]

    assert requirement["type"] == "sigstoreSigned"
    assert requirement["keyPath"].endswith("/sbt2-server.pub")
    assert "signedIdentity" not in requirement


@pytest.mark.unit
def test_registries_d_reads_the_signatures_from_registry_attachments() -> None:
    config = yaml.safe_load((DEPLOY / "registries.d" / "sbt2.yaml").read_text())

    namespace = config["docker"][SERVER_IMAGE.rsplit("/", 1)[0]]

    assert namespace["use-sigstore-attachments"] is True
