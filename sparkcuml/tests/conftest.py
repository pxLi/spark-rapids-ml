#
# Copyright (c) 2022, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Generator

import pytest
from pyspark.sql import SparkSession

dir_path = os.path.dirname(os.path.realpath(__file__))

gpu_discovery_script_path = f"{dir_path}/discover_gpu.sh"


def get_devices() -> list[str]:
    """This works only if driver is the same machine of worker."""
    completed = subprocess.run(gpu_discovery_script_path, stdout=subprocess.PIPE)
    assert completed.returncode == 0, "Failed to execute discovery script."
    msg = completed.stdout.decode("utf-8")
    result = json.loads(msg)
    addresses = result["addresses"]
    return addresses


_gpu_number = len(get_devices())
# We restrict the max gpu numbers to use
_gpu_number = _gpu_number if _gpu_number < 4 else 4


@pytest.fixture
def gpu_number() -> int:
    return _gpu_number


@pytest.fixture
def spark() -> Generator[SparkSession, None, None]:
    builder = SparkSession.builder.appName(name="spark cuml python tests")
    confs = {
        "spark.master": f"local[{_gpu_number}]",
        "spark.python.worker.reuse": "false",
        "spark.driver.host": "127.0.0.1",
        "spark.task.maxFailures": "1",
        "spark.sql.execution.pyspark.udf.simplifiedTraceback.enabled": "false",
        "spark.sql.pyspark.jvmStacktrace.enabled": "true",
    }
    for k, v in confs.items():
        builder.config(k, v)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    logging.getLogger("pyspark").setLevel(logging.WARN)
    yield spark
    spark.stop()


@pytest.fixture
def tmp_path() -> Generator[str, None, None]:
    path = tempfile.mkdtemp(prefix="spark_cuml_tests_")
    yield path
    shutil.rmtree(path)
