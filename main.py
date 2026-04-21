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
        # 1. 페이지 접속 및 충분한 대기
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3) # 추가적인 동적 로딩 대기
        
        # 2. 모든 게시글 카드 요소를 탐색 (보통 li 또는 div 구조)
        # 클래스명 대신 리스트 아이템(li)을 직접 타겟팅합니다.
        cards = await page.query_selector_all("li")
        
        for card in cards:
            text_content = await card.inner_text()
            
            # 'by.' 이라는 키워드가 있는지 확인하여 발행사 추출
            if "by." not in text_content:
                continue
                
            # 데이터 추출을 위한 정밀 분석
            # 제목(Title): 보통 가장 큰 폰트나 strong 태그
            title_el = await card.query_selector("strong, h3, .title")
            # 내용(Description): p 태그 혹은 긴 텍스트
            desc_el = await card.query_selector("p")
            # 링크(Link): 해당 카드의 a 태그
            link_el = await card.query_selector("a")
            
            if not title_el 또는 not link_el:
                continue

            raw_title = (await title_el.inner_text()).strip()
            item_desc = (await desc_el.inner_text()).strip() if desc_el else ""
            
            # 발행사 추출: "by.\n너겟" 또는 "by. 너겟" 형태 대응
            # 정규표현식으로 'by.' 뒤의 단어를 가져옵니다.
            pub_match = re.search(r'by\.\s*([\w\s가-힣]+)', text_content)
            publisher = pub_match.group(1).strip().split('\n')[0] if pub_match else "경제"
            
            # 요청하신 형식: [발행사] 제목
            final_title = f"[{publisher}] {raw_title}"
            
            # 링크 처리
            link_attr = await link_el.get_attribute("href")
            full_link = f"https://story.pay.naver.com{link_attr}" if link_attr.startswith("/") else link_attr
            
            # 날짜 추출 (패턴: 2026.04.17. 또는 24.04.17.)
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
        # 가끔 헤드리스 모드에서 데이터가 안 보일 수 있으므로 
        # 브라우저 크기를 키우고 User-Agent를 실제 PC처럼 설정합니다.
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1024},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        all_entries = await get_money_story_entries(page)
        
        if not all_entries:
            print("⚠️ 여전히 데이터를 찾지 못했습니다. 페이지가 비어있거나 구조가 완전히 다릅니다.")
            # 디버깅을 위해 페이지 텍스트를 출력해볼 수 있습니다.
            # print(await page.content()) 
            await browser.close()
            return

        # RSS 생성
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

        fg.rss_file('naverpay_story_v3.xml')
        print(f"\n✨ 완료: naverpay_story_v3.xml 생성됨 (총 {len(all_entries)}건)")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
