import asyncio
import re
from datetime import datetime, timedelta, timezone
from feedgen.feed import FeedGenerator
from playwright.async_api import async_playwright

TARGET_URL = "https://story.pay.naver.com/recent"
BASE_URL = "https://story.pay.naver.com"

# 한국 표준시(KST, UTC+9) 타임존 정의
KST = timezone(timedelta(hours=9))


def parse_date(date_text: str) -> datetime:
    """
    '6시간 전', '30분 전' 같은 상대 시간과
    '2026.10.09.', '24.10.09.' 같은 고정 날짜를 KST 타임존 datetime 객체로 변환합니다.
    """
    now = datetime.now(KST)

    # 1. 상대 시간 파싱
    hour_match = re.search(r"(\d+)\s*시간\s*전", date_text)
    if hour_match:
        return now - timedelta(hours=int(hour_match.group(1)))

    min_match = re.search(r"(\d+)\s*분\s*전", date_text)
    if min_match:
        return now - timedelta(minutes=int(min_match.group(1)))

    if "방금" in date_text:
        return now

    # 2. 고정 날짜 파싱 (YYYY.MM.DD 또는 YY.MM.DD)
    date_match = re.search(r"(\d{2,4})\.(\d{2})\.(\d{2})", date_text)
    if date_match:
        y, m, d = date_match.groups()
        year = int(f"20{y}" if len(y) == 2 else y)
        # 시간 정보가 없으므로 해당일 오전 9시 KST 기준 설정
        return datetime(year, int(m), int(d), 9, 0, 0, tzinfo=KST)

    return now


async def get_money_story_entries(page):
    entries = []
    print("🔎 게시글 카드 추출 및 시간 분석 중...")

    cards = await page.query_selector_all('a[href*="/content/"]')

    # DOM 노출 순서를 보존하기 위해 enumerate 인덱스 활용
    for idx, card in enumerate(cards):
        href = await card.get_attribute("href")
        if not href:
            continue

        full_link = f"{BASE_URL}{href}" if href.startswith("/") else href

        raw_inner_text = await card.inner_text()
        lines = [line.strip() for line in raw_inner_text.split("\n") if line.strip()]

        # 배지(N), 조회수 텍스트 필터링
        meaningful_lines = [
            l for l in lines 
            if not re.search(r"(^\bN\b|\b읽음\b|조회)", l)
        ]
        if not meaningful_lines:
            continue

        raw_title = meaningful_lines[0]

        # 날짜 문자열 감지
        raw_date_str = ""
        for line in reversed(meaningful_lines):
            if re.search(r"(\d+시간\s*전|\d+분\s*전|\d{2,4}\.\d{2}\.\d{2})", line):
                raw_date_str = line
                break

        item_dt = parse_date(raw_date_str) if raw_date_str else datetime.now(KST)

        # 요약문 및 카테고리 분리
        middle_lines = [
            l for l in meaningful_lines[1:] 
            if l != raw_date_str and not re.search(r"(\d+시간\s*전|\d+분\s*전|\d{2,4}\.\d{2}\.\d{2})", l)
        ]

        description = ""
        category = "경제"

        if len(middle_lines) >= 2:
            if len(middle_lines[0]) > len(middle_lines[1]):
                description, category = middle_lines[0], middle_lines[1]
            else:
                category, description = middle_lines[0], middle_lines[1]
        elif len(middle_lines) == 1:
            if len(middle_lines[0]) > 12:
                description = middle_lines[0]
            else:
                category = middle_lines[0]

        final_title = f"[{category}] {raw_title}"

        # 중복 방지
        if any(e["link"] == full_link for e in entries):
            continue

        entries.append({
            "order": idx,             # 원래 노출 순서 (낮을수록 상단)
            "title": final_title,
            "link": full_link,
            "description": description if description else raw_title,
            "date": item_dt
        })

    return entries


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1024},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")

        print("🔎 네이버페이 머니스토리 접속 중...")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)

        all_entries = await get_money_story_entries(page)
        await browser.close()

    if not all_entries:
        print("⚠️ 수집된 데이터가 없습니다.")
        return

    # 💡 최신 글이 위로 오도록 2중 정렬
    # 1) date 기준 최신순 (내림차순)
    # 2) 날짜가 동일하면 원본 페이지에 먼저 노출된 순서(order 오름차순) 유지
    all_entries.sort(key=lambda x: (x["date"], -x["order"]), reverse=True)

    # RSS 피드 생성
    fg = FeedGenerator()
    fg.title("네이버페이 머니스토리 RSS")
    fg.link(href=TARGET_URL, rel="alternate")
    fg.description("네이버페이 머니스토리 최신 피드")
    fg.language("ko")

    for item in all_entries[:40]:
        fe = fg.add_entry()
        fe.id(item["link"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.description(item["description"])
        # RFC 822 / RFC 2822 표준 날짜 형식 적용
        fe.pubDate(item["date"])
        print(f"✅ [{item['date'].strftime('%Y-%m-%d %H:%M')}] {item['title']}")

    output_file = "naverpay_story_v2.xml"
    fg.rss_file(output_file)
    print(f"\n✨ 정렬 완료: 최신 글 상단 배치로 '{output_file}' 저장 완료 (총 {len(all_entries)}건).")


if __name__ == "__main__":
    asyncio.run(main())
