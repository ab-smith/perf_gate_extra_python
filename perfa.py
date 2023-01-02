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

    url = args.url
    n = args.count

    driver_path = "./chromedriver"
    if not os.path.isfile(driver_path):
        print("Please download the chromedriver from https://chromedriver.chromium.org/downloads and place it in the current directory")
        exit(1)
    chrome_options.add_argument("--headless")

    for _, i in enumerate(range(n), start=1):
        print(f"Run {i+1} of {n}...", end="\r")
        driver = webdriver.Chrome(driver_path, options=chrome_options)

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

        print(raw_data)

        dns = raw_data["domainLookupEnd"] - raw_data["domainLookupStart"]
        tcp = raw_data["connectEnd"] - raw_data["connectStart"]
        ssl = raw_data["secureConnectionStart"] - raw_data["connectStart"]
        dom = raw_data["domInteractive"] - raw_data["responseStart"]
        ttfb = raw_data["responseStart"] - raw_data["fetchStart"]

        print(
            f"DNS: {dns:.2f}ms, TCP: {tcp:.2f}ms, SSL: {ssl:.2f}ms, TTFB: {ttfb:.2f}ms, DOM: {dom:.2f}ms")

        driver.quit()


def main():

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
