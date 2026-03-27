"""
PaperHub - 서빙 Lambda
논문 조회, 실시간 검색, 북마크 API
"""
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
papers_table = dynamodb.Table(os.environ['PAPERS_TABLE'])
bookmarks_table = dynamodb.Table(os.environ['BOOKMARKS_TABLE'])
pdf_bucket = os.environ['PDF_BUCKET']

# ========== 실시간 검색 API URLs ==========
PUBMED_SEARCH = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
PUBMED_FETCH = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
ARXIV_API = 'http://export.arxiv.org/api/query'
SEMANTIC_SCHOLAR_API = 'https://api.semanticscholar.org/graph/v1/paper/search'
OPENALEX_API = 'https://api.openalex.org/works'


def respond(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, ensure_ascii=False),
    }


def list_papers(event):
    """논문 목록 조회 (카테고리별 필터링)"""
    params = event.get('queryStringParameters') or {}
    category = params.get('category')
    limit = int(params.get('limit', '20'))

    if category:
        result = papers_table.query(
            IndexName='by-category',
            KeyConditionExpression=Key('category').eq(category),
            ScanIndexForward=False,
            Limit=limit,
        )
    else:
        result = papers_table.scan(Limit=limit)

    return respond(200, {
        'papers': result['Items'],
        'count': len(result['Items']),
    })


def get_paper(paper_id: str):
    """논문 상세 조회"""
    result = papers_table.query(
        KeyConditionExpression=Key('paperId').eq(paper_id),
    )
    items = result.get('Items', [])
    if not items:
        return respond(404, {'error': '논문을 찾을 수 없습니다'})
    return respond(200, items[0])


def get_pdf_url(paper_id: str):
    """PDF presigned URL 생성"""
    key = f"papers/{paper_id}.pdf"
    try:
        s3.head_object(Bucket=pdf_bucket, Key=key)
        url = s3.generate_presigned_url('get_object',
            Params={'Bucket': pdf_bucket, 'Key': key},
            ExpiresIn=3600)
        return respond(200, {'url': url})
    except s3.exceptions.ClientError:
        return respond(404, {'error': 'PDF를 찾을 수 없습니다'})


def list_bookmarks(event):
    """북마크 목록 조회"""
    params = event.get('queryStringParameters') or {}
    user_id = params.get('userId', 'default-user')
    result = bookmarks_table.query(
        KeyConditionExpression=Key('userId').eq(user_id),
    )
    return respond(200, {'bookmarks': result['Items']})


def add_bookmark(event):
    """북마크 추가"""
    body = json.loads(event.get('body', '{}'))
    user_id = body.get('userId', 'default-user')
    paper_id = body.get('paperId')
    if not paper_id:
        return respond(400, {'error': 'paperId가 필요합니다'})

    from datetime import datetime
    bookmarks_table.put_item(Item={
        'userId': user_id,
        'paperId': paper_id,
        'createdAt': datetime.utcnow().isoformat(),
    })
    return respond(201, {'message': '북마크 추가 완료'})


def delete_bookmark(event, paper_id: str):
    """북마크 삭제"""
    params = event.get('queryStringParameters') or {}
    user_id = params.get('userId', 'default-user')
    bookmarks_table.delete_item(Key={'userId': user_id, 'paperId': paper_id})
    return respond(200, {'message': '북마크 삭제 완료'})


# ========== 실시간 검색 함수들 ==========

def search_pubmed_realtime(query: str, limit: int = 10) -> list:
    """PubMed 실시간 검색"""
    try:
        params = urllib.parse.urlencode({
            'db': 'pubmed', 'term': query, 'retmax': limit,
            'sort': 'relevance', 'retmode': 'json',
        })
        with urllib.request.urlopen(f'{PUBMED_SEARCH}?{params}', timeout=10) as resp:
            data = json.loads(resp.read())
        pmids = data.get('esearchresult', {}).get('idlist', [])
        if not pmids:
            return []

        params2 = urllib.parse.urlencode({
            'db': 'pubmed', 'id': ','.join(pmids), 'retmode': 'xml',
        })
        with urllib.request.urlopen(f'{PUBMED_FETCH}?{params2}', timeout=15) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        papers = []
        for article in root.findall('.//PubmedArticle'):
            try:
                medline = article.find('.//MedlineCitation')
                pmid = medline.find('.//PMID').text
                art = medline.find('.//Article')
                title = art.find('.//ArticleTitle').text or ''
                abstract_parts = art.findall('.//Abstract/AbstractText')
                abstract = ' '.join(p.text or '' for p in abstract_parts)
                authors = []
                for a in art.findall('.//AuthorList/Author'):
                    last = a.find('LastName')
                    first = a.find('ForeName')
                    if last is not None and first is not None:
                        authors.append(f"{last.text} {first.text}")
                doi = ''
                for eid in article.findall('.//PubmedData/ArticleIdList/ArticleId'):
                    if eid.get('IdType') == 'doi':
                        doi = eid.text
                        break
                pub_date = art.find('.//Journal/JournalIssue/PubDate')
                year = pub_date.find('Year').text if pub_date is not None and pub_date.find('Year') is not None else ''
                papers.append({
                    'paperId': f'pubmed-{pmid}', 'source': 'pubmed', 'title': title,
                    'abstract': abstract, 'authors': authors, 'doi': doi,
                    'publishedDate': year, 'sourceUrl': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                })
            except Exception:
                continue
        return papers
    except Exception as e:
        print(f'PubMed search error: {e}')
        return []


def search_arxiv_realtime(query: str, limit: int = 10) -> list:
    """arXiv 실시간 검색"""
    try:
        params = urllib.parse.urlencode({
            'search_query': f'all:{query}', 'start': 0,
            'max_results': limit, 'sortBy': 'relevance',
        })
        with urllib.request.urlopen(f'{ARXIV_API}?{params}', timeout=10) as resp:
            xml_data = resp.read()

        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        root = ET.fromstring(xml_data)
        papers = []
        for entry in root.findall('atom:entry', ns):
            arxiv_id = entry.find('atom:id', ns).text.split('/abs/')[-1]
            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
            summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
            authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
            published = entry.find('atom:published', ns).text[:10]
            categories = [c.get('term') for c in entry.findall('atom:category', ns)]
            papers.append({
                'paperId': f'arxiv-{arxiv_id}', 'source': 'arxiv', 'title': title,
                'abstract': summary, 'authors': authors, 'doi': '',
                'publishedDate': published, 'category': ', '.join(categories[:3]),
                'sourceUrl': f'https://arxiv.org/abs/{arxiv_id}',
            })
        return papers
    except Exception as e:
        print(f'arXiv search error: {e}')
        return []


def search_semantic_scholar_realtime(query: str, limit: int = 10) -> list:
    """Semantic Scholar 실시간 검색 (재시도 포함)"""
    import time as _time
    for attempt in range(3):
        try:
            params = urllib.parse.urlencode({
                'query': query, 'limit': limit,
                'fields': 'paperId,title,abstract,authors,year,citationCount,externalIds,url',
            })
            req = urllib.request.Request(f'{SEMANTIC_SCHOLAR_API}?{params}')
            req.add_header('User-Agent', 'PaperHub/1.0')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            papers = []
            for p in data.get('data', []):
                if not p.get('title'):
                    continue
                doi = (p.get('externalIds') or {}).get('DOI', '')
                papers.append({
                    'paperId': f"ss-{p['paperId']}", 'source': 'semantic_scholar',
                    'title': p['title'], 'abstract': p.get('abstract') or '',
                    'authors': [a.get('name', '') for a in (p.get('authors') or [])],
                    'doi': doi, 'publishedDate': str(p.get('year', '')),
                    'citationCount': p.get('citationCount', 0),
                    'sourceUrl': p.get('url', ''),
                })
            return papers
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                _time.sleep(2 * (attempt + 1))
                continue
            print(f'Semantic Scholar search error: {e}')
            return []
        except Exception as e:
            print(f'Semantic Scholar search error: {e}')
            return []
    return []


def live_search(event):
    """실시간 멀티소스 검색"""
    params = event.get('queryStringParameters') or {}
    query = params.get('q', '')
    source = params.get('source', 'all')
    limit = min(int(params.get('limit', '10')), 30)

    if not query:
        return respond(400, {'error': '검색어(q)가 필요합니다'})

    results = []
    if source in ('all', 'pubmed'):
        results.extend(search_pubmed_realtime(query, limit))
    if source in ('all', 'arxiv'):
        results.extend(search_arxiv_realtime(query, limit))
    if source in ('all', 'semantic_scholar', 'openalex'):
        results.extend(search_openalex_realtime(query, limit))

    # 중복 제거 (제목 기반)
    seen_titles = set()
    unique = []
    for p in results:
        title_key = p['title'].lower().strip()[:80]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique.append(p)

    return respond(200, {
        'papers': unique[:limit * 2],
        'count': len(unique[:limit * 2]),
        'query': query,
        'sources': source,
    })


def search_openalex_realtime(query: str, limit: int = 10) -> list:
    """OpenAlex 실시간 검색 (2억+ 논문, 무료, 관대한 rate limit)"""
    try:
        params = urllib.parse.urlencode({
            'search': query,
            'per_page': limit,
            'select': 'id,title,authorships,publication_date,doi,cited_by_count,primary_location,abstract_inverted_index',
            'mailto': 'paperhub@example.com',
        })
        req = urllib.request.Request(f'{OPENALEX_API}?{params}')
        req.add_header('User-Agent', 'PaperHub/1.0 (mailto:paperhub@example.com)')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        papers = []
        for w in data.get('results', []):
            if not w.get('title'):
                continue
            # abstract 복원 (inverted index → text)
            abstract = ''
            aii = w.get('abstract_inverted_index')
            if aii:
                word_positions = []
                for word, positions in aii.items():
                    for pos in positions:
                        word_positions.append((pos, word))
                word_positions.sort()
                abstract = ' '.join(w for _, w in word_positions)

            authors = [a.get('author', {}).get('display_name', '') for a in (w.get('authorships') or [])[:10]]
            doi = (w.get('doi') or '').replace('https://doi.org/', '')
            source_url = ''
            loc = w.get('primary_location') or {}
            if loc.get('landing_page_url'):
                source_url = loc['landing_page_url']

            papers.append({
                'paperId': f"oa-{w['id'].split('/')[-1]}",
                'source': 'openalex',
                'title': w['title'],
                'abstract': abstract,
                'authors': authors,
                'doi': doi,
                'publishedDate': w.get('publication_date', ''),
                'citationCount': w.get('cited_by_count', 0),
                'sourceUrl': source_url,
            })
        return papers
    except Exception as e:
        print(f'OpenAlex search error: {e}')
        return []


def handler(event, context):
    """메인 라우터"""
    method = event.get('httpMethod', '')
    path = event.get('resource', '')
    path_params = event.get('pathParameters') or {}

    if path == '/papers' and method == 'GET':
        return list_papers(event)
    elif path == '/papers/{id}' and method == 'GET':
        return get_paper(path_params['id'])
    elif path == '/search' and method == 'GET':
        return live_search(event)
    elif path == '/trends' and method == 'GET':
        return get_trends(event)
    elif path == '/citations' and method == 'GET':
        return get_citations(event)
    elif path == '/bookmarks' and method == 'GET':
        return list_bookmarks(event)
    elif path == '/bookmarks' and method == 'POST':
        return add_bookmark(event)
    elif path == '/bookmarks/{paperId}' and method == 'DELETE':
        return delete_bookmark(event, path_params['paperId'])
    else:
        return respond(404, {'error': 'Not found'})


def get_trends(event):
    """연구 트렌드 - 연도별 논문 수 (OpenAlex group-by)"""
    params = event.get('queryStringParameters') or {}
    query = params.get('q', '')
    if not query:
        return respond(400, {'error': '검색어(q)가 필요합니다'})
    try:
        url_params = urllib.parse.urlencode({
            'search': query,
            'group_by': 'publication_year',
            'mailto': 'paperhub@example.com',
        })
        req = urllib.request.Request(f'{OPENALEX_API}?{url_params}')
        req.add_header('User-Agent', 'PaperHub/1.0')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        groups = data.get('group_by', [])
        # 최근 20년만
        trend = [{'year': g['key'], 'count': g['count']}
                 for g in groups if str(g.get('key', '')).isdigit() and int(g['key']) >= 2005]
        trend.sort(key=lambda x: x['year'])
        return respond(200, {'query': query, 'trends': trend})
    except Exception as e:
        print(f'Trends error: {e}')
        return respond(500, {'error': str(e)})


def get_citations(event):
    """이 논문을 인용한 논문 목록 (OpenAlex)"""
    params = event.get('queryStringParameters') or {}
    doi = params.get('doi', '')
    title = params.get('title', '')
    if not doi and not title:
        return respond(400, {'error': 'doi 또는 title이 필요합니다'})
    try:
        # DOI로 OpenAlex work ID 찾기
        if doi:
            search_url = f'https://api.openalex.org/works/doi:{doi}?mailto=paperhub@example.com'
        else:
            search_url = f'https://api.openalex.org/works?search={urllib.parse.quote(title)}&per_page=1&mailto=paperhub@example.com'

        req = urllib.request.Request(search_url)
        req.add_header('User-Agent', 'PaperHub/1.0')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        work_id = ''
        if doi and 'id' in data:
            work_id = data['id']
        elif 'results' in data and data['results']:
            work_id = data['results'][0]['id']

        if not work_id:
            return respond(200, {'citations': [], 'count': 0})

        # 인용한 논문 가져오기
        cite_url = f'https://api.openalex.org/works?filter=cites:{work_id.split("/")[-1]}&per_page=10&sort=cited_by_count:desc&select=id,title,authorships,publication_date,doi,cited_by_count&mailto=paperhub@example.com'
        req2 = urllib.request.Request(cite_url)
        req2.add_header('User-Agent', 'PaperHub/1.0')
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            cite_data = json.loads(resp2.read())

        citations = []
        for w in cite_data.get('results', []):
            authors = [a.get('author', {}).get('display_name', '') for a in (w.get('authorships') or [])[:5]]
            citations.append({
                'title': w.get('title', ''),
                'authors': authors,
                'year': w.get('publication_date', '')[:4],
                'doi': (w.get('doi') or '').replace('https://doi.org/', ''),
                'citationCount': w.get('cited_by_count', 0),
            })
        return respond(200, {'citations': citations, 'count': len(citations)})
    except Exception as e:
        print(f'Citations error: {e}')
        return respond(200, {'citations': [], 'count': 0})
