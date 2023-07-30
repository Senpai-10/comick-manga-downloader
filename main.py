import argparse
import os
import re
import time

import requests
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Column
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement


def extract_chapter_number(text: str) -> str:
    regex = re.compile(r"chapter-[0-9]*\.?[0-9]")

    m = regex.search(text)

    if m:
        return m.group().split("-")[1]

    return "0"


def extract_page_number(text: str) -> str:
    regex = re.compile(r"page [0-9]*")

    m = regex.search(text)

    if m:
        return m.group().split()[1]

    return "0"


def extract_file_extension(text: str):
    ext = text.split("/")[-1].split(".")

    if len(ext) >= 2:
        return ext[-1]
    else:
        return "jpg"


def is_cover_image(image_src: str) -> bool:
    regex = re.compile(r"/[0-9]*-")

    m = regex.search(image_src)

    if m == None:
        return True
    else:
        return False


def find_next_chapter_button(driver: WebDriver):
    buttons = driver.find_elements(By.TAG_NAME, "button")

    for button in buttons:
        if "Next" in button.text:
            return button


def download_images(driver: WebDriver, output_directory: str, chapter: str):
    img_elements = driver.find_elements(By.TAG_NAME, "img")

    images = []

    for img in img_elements:
        src = img.get_attribute("src")

        if not src or not ".pictures/" in src:
            continue

        if is_cover_image(src):
            file_ext = extract_file_extension(src)
            if not os.path.exists(f"{output_directory}/cover.{file_ext}"):
                print("downloading cover image")
                with open(f"{output_directory}/cover.{file_ext}", "wb") as f:
                    f.write(requests.get(src).content)
            continue

        images.append(img)

    for image in images:
        image_src = image.get_attribute("src")
        image_alt = image.get_attribute("alt")

        if image_alt:
            page = extract_page_number(image_alt)

            print(f"Downloading: page: {page}, chapter: {chapter}")

            if not os.path.exists(f"{output_directory}/chapters/{chapter}"):
                os.mkdir(f"{output_directory}/chapters/{chapter}")

            if image_src != None:
                file_extension = extract_file_extension(image_src)
                with open(
                    f"{output_directory}/chapters/{chapter}/{page}.{file_extension}",
                    "wb",
                ) as f:
                    f.write(requests.get(image_src).content)
                print("Done.")

    print("done downloading")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url", type=str, required=True, help="Chapter url to start downloading from"
    )
    parser.add_argument(
        "--cf-clearance",
        type=str,
        required=False,
        help="Cloud flare clearance key, used to not be detected as a bot",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=False,
        help="Output directory (Default: use manga name in the url)",
    )
    parser.add_argument(
        "--stop-after",
        type=str,
        required=False,
        help="Stop downloading after n chapter (Example: --stop-after 10, will not download anything after chapter 10)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload chapters",
    )

    args = parser.parse_args()

    url: str = args.url
    cf_clearance: str = args.cf_clearance or os.getenv("CF_CLEARANCE") or ""
    output_directory: str = args.output or url.split("/")[-2]
    stop_after: str = args.stop_after
    force_redownload: bool = args.force

    assert len(cf_clearance) != 0

    options = Options()

    options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    print(f"Opening web browser, please wait!")
    driver = webdriver.Firefox(options=options)

    driver.get(url)
    driver.delete_cookie("cf_clearance")
    driver.add_cookie({"name": "cf_clearance", "value": cf_clearance})

    if not os.path.exists(output_directory):
        os.mkdir(output_directory)
    if not os.path.exists(f"{output_directory}/chapters"):
        os.mkdir(f"{output_directory}/chapters")

    try:
        view_page_button = driver.find_element(
            By.XPATH,
            "/html/body/div[2]/div/div/div/div[2]/div[2]/div/div/div/div[3]/div/button",
        )

        print("skipping age verification")
        view_page_button.click()
    except NoSuchElementException:
        # No view page button found!
        ...

    while True:
        chapter = extract_chapter_number(driver.current_url)

        if (
            os.path.exists(f"{output_directory}/chapters/{chapter}")
            and force_redownload == False
        ):
            print(f"chapter: {chapter}, already downloaded skipping")
        else:
            download_images(driver, output_directory, chapter)

        if chapter == stop_after:
            print(f"Max chapters to download reached! (Limit: {stop_after})")
            break

        next_chapter_button: WebElement | None = find_next_chapter_button(driver)
        if next_chapter_button:
            print("next chapter")
            next_chapter_button.click()
        else:
            print("Last chapter reached")
            break

        time.sleep(1)

    driver.close()


if __name__ == "__main__":
    main()
