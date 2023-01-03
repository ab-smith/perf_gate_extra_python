import requests
import numpy as np
import pandas as pd
import argparse
from rich import print
from rich.console import Console
import time
import sys
from selenium import webdriver
import os.path
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
import subprocess
import json

chrome_options = Options()

parser = argparse.ArgumentParser()
parser.add_argument("--url", help="URL to measure target",
                    type=str, required=True)
parser.add_argument("--count", help="Number of runs. Default: 20",
                    type=int, required=False, default=20)
parser.add_argument(
    "--reference", help="reference URL to compare with. Not implemented yet", required=False)
parser.add_argument("--verbose", help="increase verbosity. Default: Disabled",
                    action=argparse.BooleanOptionalAction)
parser.add_argument(
    "--gate", help="Perf gate to control program output. Default: Disabled", action=argparse.BooleanOptionalAction)
parser.add_argument(
    "--browsermode", help="Gather metrics using headless chrome. Default: Disabled", action=argparse.BooleanOptionalAction)
parser.add_argument(
    "--output", help="Output file to save results. Optional", action="store_true")
parser.add_argument(
    "--threshold", help="Threshold for the gate in ms. Default 2000", type=int, default=2000)
parser.add_argument(
    "--lighthouse", help="Run lighthouse on the target URL. Default: Disabled. You need to install the CLI with npm first", action=argparse.BooleanOptionalAction)
parser.add_argument(
    "--write", help="Write the lighthouse results to a file. Default: Disabled", action=argparse.BooleanOptionalAction)

args = parser.parse_args()
console = Console()


def measure_ttfb(url):

    headers = {
        'User-Agent': 'Spark/PerfGate',
    }

    start = time.perf_counter()
    response = requests.get(url, headers=headers)
    elapsed = time.perf_counter() - start
    if args.verbose:
        print(f"TTFB: {elapsed*1000:.2f}ms, Status: {response.status_code}")
    return elapsed*1000


def print_stats(ttfb_array):
    print(f"Mean: {np.mean(ttfb_array):.2f}")
    print(f"Median: {np.median(ttfb_array):.2f}")
    print(f"Standard Deviation: {np.std(ttfb_array):.2f}")
    print(f"Slowest: {np.max(ttfb_array):.2f}")
    print(f"Fastest: {np.min(ttfb_array):.2f}")
    print(f"95th percentile: {np.percentile(ttfb_array, 95):.2f}")
    print(f"99th percentile: {np.percentile(ttfb_array, 99):.2f}")


def browser_mode():

    print(">> Running in browser mode for performance API")

    url = args.url
    n = args.count

    driver_path = "./chromedriver"
    if not os.path.isfile(driver_path):
        print("Please download the chromedriver from https://chromedriver.chromium.org/downloads and place it in the current directory")
        exit(1)
    chrome_options.add_argument("--headless")
    # Creating a service object
    service= Service("./chromedriver")
    for _, i in enumerate(range(n), start=1):
        print(f"Run {i+1} of {n}...", end="\r")
        driver = webdriver.Chrome(service=service)

        driver.get(url)
        try:
            sb = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "searchBar")))
        except TimeoutException:
            print("Timeout reached without detecting the element. Skipping this run...")
            driver.quit()
            continue

        raw_data = driver.execute_script(
            "return window.performance.getEntries()")[0]

        dns = raw_data["domainLookupEnd"] - raw_data["domainLookupStart"]
        tcp = raw_data["connectEnd"] - raw_data["connectStart"]
        ssl = raw_data["secureConnectionStart"] - raw_data["connectStart"]
        dom = raw_data["domInteractive"] - raw_data["responseStart"]
        ttfb = raw_data["responseStart"] - raw_data["fetchStart"]

        if args.verbose:
            print(raw_data)
            print(
                f"DNS: {dns:.2f}ms, TCP: {tcp:.2f}ms, SSL: {ssl:.2f}ms, TTFB: {ttfb:.2f}ms, DOM: {dom:.2f}ms")

        driver.quit()


def lighthouse_mode(preset=None):
    # need lightouse installed globally using npm
    # npm install -g lighthouse
    # Default preset is mobile
    print(f">> Running the lighthouse audit in {preset} mode")
    if preset=='mobile':
        print(">> Mobile mode emulates a slow device: Moto G4 on a 4G connection")
    url = args.url
    n = args.count
    tmp_list = list()
    for _, i in enumerate(range(n), start=1):
        print(f"Run {i+1} of {n}...", end="\r")
        # will use the lighthouse binary to run the audit
        if preset == "desktop":
            lighthouse = subprocess.Popen(['lighthouse', url, '--output=json', '--preset=desktop', '--only-cateogries=performance',
                                           'throttling-method=provided', '--chrome-flags="--headless"', '--quiet', '--output-path=./lighthouse.json'], stdout=subprocess.PIPE)
        if preset == "mobile":
            lighthouse = subprocess.Popen(['lighthouse', url, '--output=json', '--only-cateogries=performance',
                                           'throttling-method=provided', '--chrome-flags="--headless"', '--quiet', '--output-path=./lighthouse.json'], stdout=subprocess.PIPE)
        # wait for the process to finish
        lighthouse.wait()
        # I'm dumping the output to a file on purpose for debugging and analysis but can be used on the stdout pipe directly
        # load the json
        output = dict()
        with open('./lighthouse.json') as json_file:
            output = json.load(json_file)
        # Key metrics

        FCP = output['audits']['first-contentful-paint']['numericValue']
        LCP = output['audits']['largest-contentful-paint']['numericValue']
        TBT = output['audits']['total-blocking-time']['numericValue']

        # print these metrics
        if args.verbose:
            print(
                f"LCP: {LCP:.2f} FCP: {FCP:.2f} TBT: {TBT:.2f}")
        tmp_list.append({'FCP': FCP, 'LCP': LCP, 'TBT': TBT})
    df = pd.DataFrame.from_records(tmp_list)
    print(df.describe())
    # need the 95 and 99 percentile for the data frame
    print(df.quantile([0.95, 0.99]))


def main():

    print(">> Running the requests mode (main)")

    url = args.url
    reference_url = args.reference
    n = args.count

    if args.gate:
        print(
            f"Gate mode detected. Script will fail if 95th percentile is above {args.threshold}ms")

    if not args.verbose:
        print(f"Quiet mode. Measuring {n} times. Please wait...")
    ttfb_array_tgt = np.array([])
    for _, i in enumerate(range(n), start=1):
        print(f"Run {i} of {n}...", end="\r")
        ttfb = measure_ttfb(url)
        ttfb_array_tgt = np.append(ttfb_array_tgt, ttfb)

    print(f">> Target URL: {url}")
    print_stats(ttfb_array_tgt)

    if args.gate:
        metric = np.percentile(ttfb_array_tgt, 95)
        if metric > args.threshold:
            console.print(
                f"[bold red]Gate failed. Analyzed TTFB is {np.mean(ttfb_array_tgt):.2f}ms[/bold red]")
            sys.exit(1)
        else:
            console.print(
                f"[bold green]Gate passed. Analyzed TTFB is {np.mean(ttfb_array_tgt):.2f}ms[/bold green]")


if __name__ == "__main__":
    main()
    if args.browsermode:
        browser_mode()
    if args.lighthouse:
        lighthouse_mode(preset="desktop")
        lighthouse_mode(preset="mobile")
