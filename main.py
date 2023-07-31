import argparse
import os
import re
import time
import random

import requests
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

# from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver

import undetected_chromedriver as uc
from dataclasses import dataclass, field


@dataclass
class Page:
    number: str
    image_url: str


@dataclass
class Chapter:
    id: str
    number: str
    url: str
    pages: list[Page] = field(default_factory=list)


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


def find_next_chapter_button(driver: WebDriver) -> str | None:
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    div = driver.find_element(
        By.CSS_SELECTOR, ".images-reader-container > div:nth-child(2)"
    )

    a_tags = div.find_elements(By.TAG_NAME, "a")

    for i in a_tags:
        text = i.find_elements(By.TAG_NAME, "button")[0].text
        if text.startswith("Next"):
            print(i.get_attribute("href"))
            return i.get_attribute("href")


def collect_pages(driver: WebDriver) -> list[Page]:
    img_elements = driver.find_elements(By.TAG_NAME, "img")

    pages = []

    for image in img_elements:
        image_src = image.get_attribute("src")
        image_alt = image.get_attribute("alt")

        if not image_src or not ".pictures/" in image_src:
            continue

        if image_alt:
            page_number = extract_page_number(image_alt)

            page = Page(page_number, image_src)

            pages.append(page)

    return pages


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

    progress_bar = Progress(
        TextColumn(f"Chapter {chapter}"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
    )

    with progress_bar as p:
        for image in p.track(images, description=f"Downloading chapter {chapter}"):
            image_src = image.get_attribute("src")
            image_alt = image.get_attribute("alt")

            if image_alt:
                page = extract_page_number(image_alt)

                if not os.path.exists(f"{output_directory}/chapters/{chapter}"):
                    os.mkdir(f"{output_directory}/chapters/{chapter}")

                if image_src != None:
                    file_extension = extract_file_extension(image_src)
                    with open(
                        f"{output_directory}/chapters/{chapter}/{page}.{file_extension}",
                        "wb",
                    ) as f:
                        f.write(requests.get(image_src).content)


def expand_range(num: str) -> list[str]:
    l = []

    start, end = num.split("-")
    for j in range(int(start), int(end) + 1):
        l.append(str(j))

    return l


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url", type=str, required=True, help="Chapter url to start downloading from"
    )
    parser.add_argument(
        "--output",
        type=str,
        required=False,
        help="Output directory (Default: use manga name in the url)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload all chapters",
    )
    parser.add_argument(
        "--chapters",
        type=str,
        required=False,
        default="*",
        help="Stop downloading after n chapter (Example: --stop-after 10, will not download anything after chapter 10)",
    )

    args = parser.parse_args()

    url: str = args.url
    output_directory: str = args.output or url.split("/")[-2]
    force_redownload: bool = args.force
    chapters_str: str = args.chapters
    chapters_to_download: list[str] = []

    if "," in chapters_str:
        num = chapters_str.split(",")

        for i in num:
            if "-" in i:
                for j in expand_range(i):
                    chapters_to_download.append(j)
            else:
                chapters_to_download.append(i)
    else:
        if "-" in chapters_str:
            for j in expand_range(chapters_str):
                chapters_to_download.append(j)
        else:
            chapters_to_download.append(chapters_str)

    assert len(url) != 0

    options = Options()

    options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    print(f"Opening web browser, please wait!")
    driver = uc.Chrome(options)
    driver.get(url)

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

    info_container = driver.find_elements(By.CLASS_NAME, "info-reader-container")[0]

    selectors = info_container.find_elements(By.TAG_NAME, "select")[0]
    manga_url = "/".join(list(url.split("/")[0:-1]))
    chapters: list[Chapter] = []

    # Collecting chapters
    for option in selectors.find_elements(By.TAG_NAME, "option")[::-1]:
        chapter_id = option.get_attribute("value")

        text = option.text
        chapter_number = ""

        if " " in text:
            chapter_number = text.split()[1]
        else:
            chapter_number = text

        if not chapter_id:
            continue

        ch = Chapter(
            chapter_id,
            chapter_number,
            f"{manga_url}/{chapter_id}-chapter-{chapter_number}-en",
        )

        if "*" in chapters_to_download or ch.number in chapters_to_download:
            chapters.append(ch)

    # Collecting pages
    for chapter in chapters:
        driver.get(chapter.url)

        print(f"Collecting pages for chapter {chapter.number}")
        chapter.pages = collect_pages(driver)

    if not os.path.exists(output_directory):
        os.mkdir(output_directory)
    if not os.path.exists(f"{output_directory}/chapters"):
        os.mkdir(f"{output_directory}/chapters")

    # while True:
    #     chapter = extract_chapter_number(driver.current_url)

    #     if (
    #         os.path.exists(f"{output_directory}/chapters/{chapter}")
    #         and force_redownload == False
    #         and not chapter in force_redownload_chapter
    #     ):
    #         print(f"chapter: {chapter}, already downloaded skipping")
    #     else:
    #         download_images(driver, output_directory, chapter)

    #     if chapter == stop_after:
    #         print(f"Max chapters to download reached! (Limit: {stop_after})")
    #         break

    #     next_chapter_button: str | None = find_next_chapter_button(driver)

    #     if next_chapter_button == None:
    #         print("Last chapter reached")
    #         break

    #     time.sleep(random.uniform(2.130, 2.267))
    #     print("Next chapter")
    #     driver.get(next_chapter_button)

    #     time.sleep(random.uniform(1.213, 1.345))

    driver.close()


if __name__ == "__main__":
    main()
