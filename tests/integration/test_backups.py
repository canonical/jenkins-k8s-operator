#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import logging
import os
import socket
import subprocess
import uuid
from pathlib import Path

import boto3
import pytest
from pytest_operator.plugin import OpsTest

from . import juju_
from .helpers import (
    execute_queries_on_unit,
    get_server_config_credentials,
    get_unit_address,
    rotate_credentials,
    scale_application,
)
from .high_availability.high_availability_helpers import (
    deploy_and_scale_mysql,
    insert_data_into_mysql_and_validate_replication,
)

logger = logging.getLogger(__name__)

host_ip = socket.gethostbyname(socket.gethostname())

S3_INTEGRATOR = "s3-integrator"
TIMEOUT = 10 * 60
CLUSTER_ADMIN_PASSWORD = "clusteradminpassword"
SERVER_CONFIG_PASSWORD = "serverconfigpassword"
ROOT_PASSWORD = "rootpassword"
DATABASE_NAME = "backup-database"
TABLE_NAME = "backup-table"

backups_by_cloud = {}
value_before_backup, value_after_backup = None, None


@dataclasses.dataclass(frozen=True)
class ConnectionInformation:
    access_key_id: str
    secret_access_key: str
    bucket: str


@pytest.fixture(scope="session")
def microceph():
    if not os.environ.get("CI") == "true":
        raise Exception("Not running on CI. Skipping microceph installation")
    logger.info("Setting up microceph")
    subprocess.run(["sudo", "snap", "install", "microceph"], check=True)
    subprocess.run(["sudo", "microceph", "cluster", "bootstrap"], check=True)
    subprocess.run(["sudo", "microceph", "disk", "add", "loop,4G,3"], check=True)
    subprocess.run(["sudo", "microceph", "enable", "rgw"], check=True)
    output = subprocess.run(
        [
            "sudo",
            "microceph.radosgw-admin",
            "user",
            "create",
            "--uid",
            "test",
            "--display-name",
            "test",
        ],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    key = json.loads(output)["keys"][0]
    key_id = key["access_key"]
    secret_key = key["secret_key"]
    logger.info("Creating microceph bucket")
    boto3.client(
        "s3",
        endpoint_url="http://localhost",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_key,
    ).create_bucket(Bucket=_BUCKET)
    logger.info("Set up microceph")
    return ConnectionInformation(key_id, secret_key, _BUCKET)


_BUCKET = "testbucket"


@pytest.fixture(scope="session")
def cloud_credentials(microceph: ConnectionInformation) -> dict[str, dict[str, str]]:
    """Read cloud credentials."""
    return {
        "ceph": {
            "access-key": microceph.access_key_id,
            "secret-key": microceph.secret_access_key,
        },
    }


def test_boto3(cloud_credentials):
    logger.info("CLOUD CREDS: %s", cloud_credentials)
