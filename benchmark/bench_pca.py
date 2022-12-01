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

import argparse
import time
from typing import List, Union

import numpy as np
import pandas as pd
from pyspark.ml.feature import PCA
from pyspark.ml.functions import array_to_vector
from pyspark.sql import SparkSession
from pyspark.sql import DataFrame

from sparkcuml.decomposition import SparkCumlPCA


def prepare_spark_session(spark_confs: List[str]) -> SparkSession:
    builder = SparkSession.builder
    for sconf in spark_confs:
        key, value = sconf.split("=")
        builder = builder.config(key, value)
    spark = builder.getOrCreate()
    return spark

def prepare_df(spark: SparkSession, num_vecs: int, dim: int, num_partitions: int, dtype: Union[np.float64, np.float32], input_col: str) -> DataFrame: 
    data = np.random.rand(num_vecs, dim).astype(dtype).tolist()
    rdd = spark.sparkContext.parallelize(data, num_partitions).map(lambda row: (row,))
    df = rdd.toDF([input_col])
    return df

def test_pca_bench(
    run_id: int, 
    num_vecs: int,
    dim: int,
    n_components: int,
    num_gpus: int,
    num_cpus: int,
    dtype: Union[np.float64, np.float32],
    spark_confs: List[str],
) -> pd.DataFrame:

    func_start_time = time.time()
    input_col = "features"
    output_col = "pca_features"

    report_row = {
        "run_id": run_id, 
        "fit": None,
        "transform": None,
        "total": None,
        "num_vecs": num_vecs,
        "dim": dim,
        "n_components": n_components,
        "num_gpus": num_gpus,
        "num_cpus": num_cpus,
        "dtype": dtype,
    }

    for sconf in spark_confs:
        key, value = sconf.split("=")
        report_row[key] = value

    report_pd = pd.DataFrame(columns = report_row.keys())

    spark = prepare_spark_session(spark_confs)

    if num_gpus > 0:
        assert num_cpus <= 0
        start_time = time.time()
        df = prepare_df(spark, num_vecs, dim, num_gpus, dtype, input_col).cache()
        df.count()
        print(f"gen_dataset of {num_gpus} partitions took: {time.time() - start_time} sec")

        start_time = time.time()
        gpu_pca = (
            SparkCumlPCA(num_workers=num_gpus)
            .setInputCol(input_col)
            .setOutputCol(output_col)
            .setK(n_components)
        )
        gpu_model = gpu_pca.fit(df)
        report_row["fit"] = time.time() - start_time
        print(f"gpu fit took: {report_row['fit']} sec")

        start_time = time.time()
        gpu_model.transform(df).count()
        report_row["transform"] = time.time() - start_time
        print(f"gpu transform took: {report_row['transform']} sec")

        report_row['total'] = time.time() - func_start_time
        print(f"gpu total took: {report_row['total']} sec")
        report_pd.loc["sparkcuml_pca"] = report_row

    if num_cpus > 0:
        assert num_gpus <= 0
        start_time = time.time()
        df = prepare_df(spark, num_vecs, dim, num_cpus, dtype, input_col)
        vector_df = df.select(array_to_vector(df[input_col]).alias(input_col)).cache()
        vector_df.count()
        print(f"gen_dataset of {num_cpus} partitions took: {time.time() - start_time} sec")

        start_time = time.time()
        cpu_pca = PCA().setInputCol(input_col).setOutputCol(output_col).setK(n_components)
        cpu_model = cpu_pca.fit(vector_df)
        report_row["fit"] = time.time() - start_time
        print(f"cpu fit took: {report_row['fit']} sec")

        start_time = time.time()
        cpu_model.transform(vector_df).count()  
        report_row["transform"] = time.time() - start_time
        print(f"cpu transform took: {report_row['transform']} sec")

        report_row['total'] = time.time() - func_start_time
        print(f"cpu total took: {report_row['total']} sec")
        report_pd.loc["spark_pca"] = report_row

    return report_pd


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_vecs", type=int, default=5000)
    parser.add_argument("--dim", type=int, default=2000)
    parser.add_argument("--n_components", type=int, default=3)
    parser.add_argument("--num_gpus", type=int, default=1, help='number of available GPUs. If num_gpus > 0, sparkcuml will run with the number of dataset partitions equal to num_gpus.')
    parser.add_argument("--num_cpus", type=int, default=6, help='number of available CPUs. If num_cpus > 0, spark will run and with the number of dataset partitions to num_cpus.')
    parser.add_argument("--dtype", type=str, choices=["float64"], default="float64")
    parser.add_argument("--num_runs", type=int, default=2, help='set the number of repetitions for cold/warm runs')
    parser.add_argument("--report_path", type=str, default="")
    parser.add_argument("--spark_confs", action="append", default=[])
    args = parser.parse_args()

    report_pd = pd.DataFrame()
    for run_id in range(args.num_runs):
        rpd = test_pca_bench(
            run_id, 
            args.num_vecs,
            args.dim,
            args.n_components,
            args.num_gpus,
            args.num_cpus,
            args.dtype,
            args.spark_confs,
        )
        print(rpd)
        report_pd = pd.concat([report_pd, rpd])

    print(f"\nsummary of the total {args.num_runs} runs:\n")
    print(report_pd)
    if args.report_path != "":
        report_pd.to_csv(args.report_path, mode="a")
