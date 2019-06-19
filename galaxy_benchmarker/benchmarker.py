from typing import Dict
import workflow
import destination
import benchmark
from galaxy_bridge import Galaxy
import logging
import json
from influxdb_bridge import InfluxDB


log = logging.getLogger("GalaxyBenchmarker")


class Benchmarker:
    glx: Galaxy
    inflx_db: InfluxDB
    workflows: Dict[str, workflow.BaseWorkflow]
    destinations: Dict[str, destination.BaseDestination]
    benchmarks: Dict[str, benchmark.BaseBenchmark]

    def __init__(self, config):
        self.glx = Galaxy(config["galaxy"]["url"], config["galaxy"]["admin_key"], config["galaxy"]["shed_install"],
                          config["galaxy"]["ssh_user"], config["galaxy"]["ssh_key"],
                          config["galaxy"]["galaxy_root_path"], config["galaxy"]["galaxy_config_dir"],
                          config["galaxy"]["galaxy_user"])

        self.inflx_db = InfluxDB(config["influxdb"]["host"], config["influxdb"]["port"],
                                 config["influxdb"]["username"], config["influxdb"]["password"],
                                 config["influxdb"]["db_name"])

        self.workflows = dict()
        for wf_config in config["workflows"]:
            self.workflows[wf_config["name"]] = workflow.configure_workflow(wf_config)

        self.destinations = dict()
        for dest_config in config["destinations"]:
            self.destinations[dest_config["name"]] = destination.configure_destination(dest_config, self.glx)

        self.benchmarks = dict()
        for bm_config in config["benchmarks"]:
            self.benchmarks[bm_config["name"]] = benchmark.configure_benchmark(bm_config, self.destinations,
                                                                               self.workflows, self.glx)
        log.info("Creating job_conf for Galaxy and deploying it")
        destination.create_galaxy_job_conf(self.glx, self.destinations)
        self.glx.deploy_job_conf()

    def run_pre_tasks(self):
        log.info("Running pre-tasks for benchmarks")
        for bm in self.benchmarks.values():
            bm.run_pre_task()

    def run_post_tasks(self):
        log.info("Running post-tasks for benchmarks")
        for bm in self.benchmarks.values():
            bm.run_post_task()

    def run(self):
        for bm in self.benchmarks.values():
            log.info("Running benchmark '{bm_name}'".format(bm_name=bm.name))
            bm.run(self)

    def get_results(self):
        for bm in self.benchmarks.values():
            print(bm.benchmark_results)

    def save_results(self, filename="results"):
        results = list()
        for bm in self.benchmarks.values():
            results.append(bm.benchmark_results)

        json_results = json.dumps(results, indent=2)
        with open(filename+".json", "w") as fh:
            fh.write(json_results)

    def send_results_to_influxdb(self):
        for bm in self.benchmarks.values():
            bm.save_results_to_influxdb(self.inflx_db)

