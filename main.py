import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright
from feedgen.feed import FeedGenerator

TARGET_URL = "https://story.pay.naver.com/recent"

async def get_money_story_entries(page):
    entries = []
    print(f"🔎 [Log] 패턴 매칭 방식으로 데이터 추적 시작...")
    
    try:
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3) 
        
        cards = await page.query_selector_all("li")
        
        for card in cards:
            text_content = await card.inner_text()
            
            if "by." not in text_content:
                continue
                
            title_el = await card.query_selector("strong, h3, .title")
            desc_el = await card.query_selector("p")
            link_el = await card.query_selector("a")
            
            # 파이썬 예약어 'or'를 사용하여 수정 완료
            if not title_el or not link_el:
                continue

            raw_title = (await title_el.inner_text()).strip()
            item_desc = (await desc_el.inner_text()).strip() if desc_el else ""
            
            pub_match = re.search(r'by\.\s*([\w\s가-힣]+)', text_content)
            publisher = pub_match.group(1).strip().split('\n')[0] if pub_match else "경제"
            
            final_title = f"[{publisher}] {raw_title}"
            
            link_attr = await link_el.get_attribute("href")
            full_link = f"https://story.pay.naver.com{link_attr}" if link_attr.startswith("/") else link_attr
            
            date_match = re.search(r'(\d{2,4})\.(\d{2})\.(\d{2})', text_content)
            if date_match:
                y, m, d = date_match.groups()
                year = f"20{y}" if len(y) == 2 else y
                item_date = f"{year}-{m}-{d}"
            else:
                item_date = datetime.지금().strftime('%Y-%m-%d')

            entries.append({
                "title": final_title,
                "link": full_link,
                "description": item_desc,
                "date": item_date
            })
            print(f"✅ 발견: {final_title}")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        
    return entries

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1024},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        all_entries = await get_money_story_entries(page)
        
        if not all_entries:
            print("⚠️ 데이터를 찾지 못했습니다.")
            await browser.close()
            return

        fg = FeedGenerator()
        fg.title('네이버페이 머니스토리 RSS')
        fg.link(href=TARGET_URL, rel='alternate')
        fg.description('너겟 등 머니스토리 요약 정보')

        all_entries.sort(key=lambda x: x['date'], reverse=True)

        for item in all_entries[:40]:
            fe = fg.add_entry()
            fe.id(item['link'])
            fe.title(item['title'])
            fe.link(href=item['link'])
            fe.description(item['description'])
            fe.pubDate(f"{item['date']} 09:00:00 +0900")

        fg.rss_file('main.xml') # 파일명을 main.xml 혹은 원하는 이름으로 변경 가능
        print(f"\n✨ 완료: RSS 파일이 생성되었습니다.")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
