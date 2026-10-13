import hashlib
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET


SOURCE_URL = "https://keizai.info/category/general-bingo"
OUTPUT_FILE = "keizai_bingo.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}


def fetch_page():
    for attempt in range(1, 4):
        try:
            print(f"取得 {attempt}/3: {SOURCE_URL}")

            response = requests.get(
                SOURCE_URL,
                headers=HEADERS,
                timeout=30,
            )

            print(f"HTTP: {response.status_code}")
            response.raise_for_status()

            return response.text

        except requests.RequestException as e:
            print(f"取得失敗: {e}")

            if attempt < 3:
                print("10秒待って再試行します。")
                time.sleep(10)

    return None


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_issue_date(text):
    text = clean_text(text)

    match = re.search(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日号",
        text,
    )

    if not match:
        return None

    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            12,
            0,
            0,
            tzinfo=JST,
        )

    except ValueError:
        return None


def make_guid(link):
    return hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


def load_existing_items():
    items = {}

    if not os.path.exists(OUTPUT_FILE):
        return items

    try:
        tree = ET.parse(OUTPUT_FILE)
        root = tree.getroot()

        for item in root.findall("./channel/item"):
            guid = item.findtext("guid", "").strip()

            if not guid:
                continue

            items[guid] = {
                "title": item.findtext("title", ""),
                "link": item.findtext("link", ""),
                "description": item.findtext(
                    "description",
                    "",
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    "",
                ),
                "guid": guid,
            }

    except Exception as e:
        print(f"既存RSS読込失敗: {e}")

    return items


def parse_articles(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    articles = []
    seen_links = set()

    for block in soup.select("div.new-posts"):
        status_el = block.select_one(
            "div.koudokusha"
        )

        issue_el = block.select_one(
            "div.gatsugo"
        )

        title_el = block.select_one(
            "div.news_Title a[href]"
        )

        if issue_el is None or title_el is None:
            continue

        status = ""

        if status_el is not None:
            status = clean_text(
                status_el.get_text(
                    " ",
                    strip=True,
                )
            )

        issue_text = clean_text(
            issue_el.get_text(
                " ",
                strip=True,
            )
        )

        issue_date = parse_issue_date(
            issue_text
        )

        if issue_date is None:
            continue

        title = clean_text(
            title_el.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        link = urljoin(
            SOURCE_URL,
            title_el.get("href", "").strip(),
        )

        if not re.fullmatch(
            r"https://keizai\.info/general-bingo/\d+/?",
            link,
        ):
            continue

        if link in seen_links:
            continue

        seen_links.add(link)

        image_url = ""

        image = block.find("img")

        if image is not None:
            src = image.get("src", "").strip()

            if src:
                image_url = urljoin(
                    SOURCE_URL,
                    src,
                )

        articles.append(
            {
                "status": status,
                "issue": issue_text,
                "date": issue_date,
                "title": title,
                "link": link,
                "image": image_url,
            }
        )

    return articles


def build_description(article):
    parts = []

    if article["status"]:
        parts.append(
            f"区分: {article['status']}"
        )

    parts.append(
        f"掲載号: {article['issue']}"
    )

    if article["image"]:
        parts.append(
            f'<img src="{article["image"]}" '
            f'alt="{article["title"]}">'
        )

    return "<br>".join(parts)


def build_rss(existing_items, current_articles):
    now = datetime.now(JST)

    merged = dict(existing_items)
    new_count = 0

    for article in current_articles:
        guid = make_guid(
            article["link"]
        )

        description = build_description(
            article
        )

        if guid in merged:
            old_pubdate = merged[guid].get(
                "pubDate",
                "",
            )

            merged[guid] = {
                "title": article["title"],
                "link": article["link"],
                "description": description,
                "pubDate": (
                    old_pubdate
                    if old_pubdate
                    else format_datetime(
                        article["date"]
                    )
                ),
                "guid": guid,
            }

            continue

        merged[guid] = {
            "title": article["title"],
            "link": article["link"],
            "description": description,
            "pubDate": format_datetime(
                article["date"]
            ),
            "guid": guid,
        }

        new_count += 1

    def get_pubdate(item):
        try:
            dt = parsedate_to_datetime(
                item["pubDate"]
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt

        except Exception:
            return datetime(
                1970,
                1,
                1,
                tzinfo=timezone.utc,
            )

    sorted_items = sorted(
        merged.values(),
        key=get_pubdate,
        reverse=True,
    )

    rss = ET.Element(
        "rss",
        version="2.0",
    )

    channel = ET.SubElement(
        rss,
        "channel",
    )

    ET.SubElement(
        channel,
        "title",
    ).text = "びんご経済レポート ニュース 備後版"

    ET.SubElement(
        channel,
        "link",
    ).text = SOURCE_URL

    ET.SubElement(
        channel,
        "description",
    ).text = (
        "びんご経済レポート「ニュース 備後版」の"
        "公開見出し更新情報"
    )

    ET.SubElement(
        channel,
        "language",
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate",
    ).text = format_datetime(now)

    for data in sorted_items:
        item = ET.SubElement(
            channel,
            "item",
        )

        ET.SubElement(
            item,
            "title",
        ).text = data["title"]

        ET.SubElement(
            item,
            "link",
        ).text = data["link"]

        ET.SubElement(
            item,
            "description",
        ).text = data["description"]

        ET.SubElement(
            item,
            "pubDate",
        ).text = data["pubDate"]

        guid_el = ET.SubElement(
            item,
            "guid",
        )

        guid_el.set(
            "isPermaLink",
            "false",
        )

        guid_el.text = data["guid"]

    tree = ET.ElementTree(rss)

    ET.indent(
        tree,
        space="  ",
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    return len(sorted_items), new_count


def main():
    existing_items = load_existing_items()

    print(
        f"既存RSS件数: {len(existing_items)}"
    )

    html = fetch_page()

    if html is None:
        if existing_items:
            print(
                "サイトを取得できなかったため、"
                "既存XMLを維持します。"
            )
            return

        raise RuntimeError(
            "記事を取得できず、"
            "既存XMLもありません。"
        )

    articles = parse_articles(html)

    print(
        f"現在ページの記事数: {len(articles)}"
    )

    if len(articles) < 5:
        if existing_items:
            print(
                "取得記事数が異常に少ないため、"
                "既存XMLを維持します。"
            )
            return

        raise RuntimeError(
            f"取得記事数が少なすぎます: "
            f"{len(articles)}"
        )

    print()
    print("現在ページの記事:")

    for i, article in enumerate(
        articles,
        1,
    ):
        status = (
            f"[{article['status']}] "
            if article["status"]
            else ""
        )

        print(
            f"{i:2d}. "
            f"{article['issue']} "
            f"{status}"
            f"{article['title']}"
        )

        print(
            f"    {article['link']}"
        )

    total_count, new_count = build_rss(
        existing_items,
        articles,
    )

    print()
    print(
        f"今回の新規記事: {new_count}"
    )

    print(
        f"RSS保存件数: {total_count}"
    )

    print(
        "保存先: "
        f"{os.path.abspath(OUTPUT_FILE)}"
    )


if __name__ == "__main__":
    main()