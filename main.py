import argparse
from dataclasses import dataclass, field
import os
import random
import re
import time

import requests
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc


@dataclass
class Page:
    number: str
    file_extension: str
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

    return "cover"


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


COVER = None
COVER_FILE_NAME = None


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
            file_ext = extract_file_extension(image_src)

            page = Page(page_number, file_ext, image_src)

            if page.number == "cover":
                global COVER
                global COVER_FILE_NAME
                COVER = page.image_url
                COVER_FILE_NAME = f"cover.{page.file_extension}"
                continue

            pages.append(page)

    return pages


def expand_range(num: str) -> list[str]:
    l = []

    start, end = num.split("-")
    for j in range(int(start), int(end) + 1):
        l.append(str(j))

    return l


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url", type=str, required=False, help="Chapter url to get chapters list (example: 'https://comick.app/comic/bleach/AgV11-chapter-1-en')"
    )
    parser.add_argument(
        "--output",
        type=str,
        required=False,
        help="Output directory (Default: use manga name in the url)",
    )
    parser.add_argument(
        "--chapters",
        type=str,
        required=False,
        default="*",
        help="Chapters to download, can be '1,2,3,4,5'/'1,2,3,4,5-10'/'1-10','*'. A '*' to downloads all",
    )

    args = parser.parse_args()

    url: str = args.url or Prompt.ask("Enter [bold green]url[/bold green]")

    output_directory: str = args.output or url.split("/")[-2]
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

    print("Collecting chapters")
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

    print("Collecting pages")
    # Collecting pages
    for chapter in chapters:
        driver.get(chapter.url)

        print(f"Collecting pages for chapter {chapter.number}")
        chapter.pages = collect_pages(driver)

        time.sleep(random.uniform(0.100, 0.900))

    if not os.path.exists(f"{output_directory}/chapters"):
        os.makedirs(f"{output_directory}/chapters")

    if not os.path.exists(f"{output_directory}/{COVER_FILE_NAME}"):
        if COVER:
            with open(
                f"{output_directory}/{COVER_FILE_NAME}",
                "wb",
            ) as f:
                f.write(requests.get(COVER).content)

    # Download chapters
    for chapter in chapters:
        if not os.path.exists(f"{output_directory}/chapters/{chapter.number}"):
            os.mkdir(f"{output_directory}/chapters/{chapter.number}")

        progress_bar = Progress(
            TextColumn(f"Chapter {chapter.number}"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )

        with progress_bar as p:
            for page in p.track(
                chapter.pages, description=f"Downloading chapter {chapter.number}"
            ):
                with open(
                    f"{output_directory}/chapters/{chapter.number}/{page.number}.{page.file_extension}",
                    "wb",
                ) as f:
                    f.write(requests.get(page.image_url).content)

    driver.close()


if __name__ == "__main__":
    main()
