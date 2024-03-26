#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import urllib3
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import AsyncRetrying, RetryError, stop_after_delay, wait_fixed

from constants import CLUSTER_ADMIN_USERNAME, PASSWORD_LENGTH, ROOT_USERNAME
from utils import generate_random_password

from .helpers import (
    delete_file_or_directory_in_unit,
    dispatch_custom_event_for_logrotate,
    execute_queries_on_unit,
    fetch_credentials,
    generate_random_string,
    get_cluster_status,
    get_primary_unit,
    get_server_config_credentials,
    get_unit_address,
    ls_la_in_unit,
    read_contents_from_file_in_unit,
    retrieve_database_variable_value,
    rotate_credentials,
    scale_application,
    start_mysqld_exporter,
    stop_running_flush_mysql_job,
    stop_running_log_rotate_dispatcher,
    write_content_to_file_in_unit,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CLUSTER_NAME = "test_cluster"
TIMEOUT = 15 * 60


@pytest.mark.group(1)
@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build the mysql charm and deploy it."""
    async with ops_test.fast_forward("60s"):
        resources = {"mysql-image": METADATA["resources"]["mysql-image"]["upstream-source"]}
        config = {"cluster-name": CLUSTER_NAME, "profile": "testing"}
        await ops_test.model.deploy(
            "mysql-k8s",
            resources=resources,
            application_name=APP_NAME,
            config=config,
            num_units=3,
            series="jammy",
            trust=True,
            channel="8.0/edge",
            revision=132,
        )

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=TIMEOUT,
            wait_for_exact_units=3,
        )
        assert len(ops_test.model.applications[APP_NAME].units) == 3

        random_unit = ops_test.model.applications[APP_NAME].units[0]
        server_config_credentials = await get_server_config_credentials(random_unit)

        count_group_replication_members_sql = [
            "SELECT count(*) FROM performance_schema.replication_group_members where MEMBER_STATE='ONLINE';",
        ]

        for unit in ops_test.model.applications[APP_NAME].units:
            assert unit.workload_status == "active"

            unit_address = await get_unit_address(ops_test, unit.name)
            output = await execute_queries_on_unit(
                unit_address,
                server_config_credentials["username"],
                server_config_credentials["password"],
                count_group_replication_members_sql,
            )
            assert output[0] == 3


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_log_rotation(ops_test: OpsTest) -> None:
    """Test the log rotation of text files."""
    unit = ops_test.model.applications[APP_NAME].units[0]

    logger.info("Extending update-status-hook-inteval to 60m")
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    # Exclude slowquery log files as slowquery logs are not enabled by default
    log_types = ["error", "general"]
    log_files = ["error.log", "general.log"]
    archive_directories = ["archive_error", "archive_general", "archive_slowquery"]

    logger.info("Overwriting the log rotate dispatcher script")
    unit_label = unit.name.replace("/", "-")
    await write_content_to_file_in_unit(
        ops_test,
        unit,
        f"/var/lib/juju/agents/unit-{unit_label}/charm/scripts/log_rotate_dispatcher.py",
        "exit(0)\n",
        container_name="charm",
    )

    logger.info("Stopping the log rotate dispatcher")
    await stop_running_log_rotate_dispatcher(ops_test, unit.name)

    logger.info("Stopping any running logrotate jobs")
    await stop_running_flush_mysql_job(ops_test, unit.name)

    logger.info("Removing existing archive directories")
    for archive_directory in archive_directories:
        await delete_file_or_directory_in_unit(
            ops_test,
            unit.name,
            f"/var/log/mysql/{archive_directory}/",
        )

    logger.info("Writing some data to the text log files")
    for log in log_types:
        log_path = f"/var/log/mysql/{log}.log"
        await write_content_to_file_in_unit(ops_test, unit, log_path, f"test {log} content\n")

    logger.info("Ensuring only log files exist")
    ls_la_output = await ls_la_in_unit(ops_test, unit.name, "/var/log/mysql/")

    assert len(ls_la_output) == len(
        log_files
    ), f"❌ files other than log files exist {ls_la_output}"
    directories = [line.split()[-1] for line in ls_la_output]
    assert sorted(directories) == sorted(
        log_files
    ), f"❌ file other than logs files exist: {ls_la_output}"

    logger.info("Dispatching custom event to rotate logs")
    await dispatch_custom_event_for_logrotate(ops_test, unit.name)

    logger.info("Ensuring log files and archive directories exist")
    ls_la_output = await ls_la_in_unit(ops_test, unit.name, "/var/log/mysql/")

    assert len(ls_la_output) == len(
        log_files + archive_directories
    ), f"❌ unexpected files/directories in log directory: {ls_la_output}"
    directories = [line.split()[-1] for line in ls_la_output]
    assert sorted(directories) == sorted(
        log_files + archive_directories
    ), f"❌ unexpected files/directories in log directory: {ls_la_output}"

    logger.info("Ensuring log files were rotated")
    # Exclude checking slowquery log rotation as slowquery logs are disabled by default
    for log in set(log_types):
        file_contents = await read_contents_from_file_in_unit(
            ops_test, unit, f"/var/log/mysql/{log}.log"
        )
        assert f"test {log} content" not in file_contents, f"❌ log file {log}.log not rotated"

        ls_la_output = await ls_la_in_unit(ops_test, unit.name, f"/var/log/mysql/archive_{log}/")
        assert len(ls_la_output) == 1, f"❌ more than 1 file in archive directory: {ls_la_output}"

        filename = ls_la_output[0].split()[-1]
        file_contents = await read_contents_from_file_in_unit(
            ops_test,
            unit,
            f"/var/log/mysql/archive_{log}/{filename}",
        )
        assert f"test {log} content" in file_contents, f"❌ log file {log}.log not rotated"
